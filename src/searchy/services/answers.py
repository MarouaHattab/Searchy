import asyncio
import json
import re
from pathlib import Path

import anyio
import httpx

from searchy.api.exploration import GraphRequest
from searchy.core.config import Settings
from searchy.core.errors import InvalidInput, SearchyError
from searchy.domain import stable_id
from searchy.graph.explorer import GraphExplorer
from searchy.models.answers import AnswerProvider, build_prompt
from searchy.retrieval.search import (
    character_matches,
    clothing_matches,
    dialogue_matches,
    identity_key,
    normalized_terms,
    speaker_matches,
)
from searchy.retrieval.understanding import clothing_query, understand
from searchy.storage.metadata import MetadataStore
from searchy.storage.sessions import SearchSessions

MAX_DESCRIPTION = 900
MAX_EVIDENCE_PER_SCENE = 8
MAX_CONTEXT_CHARS = 42000


class AnswerService:
    def __init__(
        self,
        settings: Settings,
        metadata: MetadataStore,
        search,
        graph=None,
        transport: httpx.BaseTransport | None = None,
    ):
        self.settings, self.metadata, self.search, self.graph = settings, metadata, search, graph
        self.provider = AnswerProvider(settings, transport)

    def answer(
        self, query, scene_ids, collection_id=None, character_ids=None, search_id=None
    ) -> dict:
        async def collect():
            async for event, payload in self.stream(
                query, scene_ids, collection_id, character_ids, search_id
            ):
                if event == "answer":
                    return payload

        return asyncio.run(collect())

    def _prepare(self, query, scene_ids, collection_id, character_ids):
        requested = self.search.requested_characters(query, collection_id)
        plan = understand(query, requested)
        response = {
            "status": "insufficient_evidence",
            "answer": "",
            "markdown": "",
            "claims": [],
            "citations": [],
            "evidence": [],
            "relationships": [],
            "constraints": [],
            "warnings": [],
            "provider": None,
            "model": None,
            "query_type": plan.primary_type,
            "graph": {
                "nodes": [],
                "edges": [],
                "scene_ids": [],
                "warnings": [],
                "truncated": False,
            },
            "retrieval": {"strategy": "hybrid_graph_context", "graph_used": False},
        }
        scenes, blocks = [], []
        for scene_id in scene_ids[:6]:
            scene = self.metadata.get_scene(scene_id)
            if scene is None:
                raise SearchyError("A requested scene was not found", 404)
            if collection_id is not None and scene.collection_id != collection_id:
                raise InvalidInput("Requested scenes must belong to the selected collection")
            if not self.metadata.is_indexed(scene_id):
                raise SearchyError("A requested scene is not currently indexed", 409)
            missing = self._constraints(query, scene, requested, character_ids)
            if missing is None:
                continue
            evidence = self._select_evidence(scene, query, character_ids)
            if not evidence:
                continue
            scenes.append(scene)
            blocks.append(
                {
                    "scene_id": scene_id,
                    "episode_id": scene.episode_id,
                    "start": scene.start,
                    "end": scene.end,
                    "timestamp_basis": scene.timestamp_basis,
                    "missing_terms": missing,
                }
            )
            response["evidence"].extend(evidence)
        if not scenes:
            response["warnings"].append(
                "No retrieved scene contains enough evidence to answer this question."
            )
            return response, {}, scenes
        if plan.temporal and self.graph is not None:
            try:
                neighbors = self.graph.neighbors([s.scene_id for s in scenes[:4]], collection_id)
                videos = {s.video_id for s in scenes}
                for identifier in neighbors:
                    if len(scenes) >= 12 or identifier in {s.scene_id for s in scenes}:
                        continue
                    nearby = self.metadata.get_scene(identifier)
                    if (
                        nearby is None
                        or nearby.video_id not in videos
                        or not self.metadata.is_indexed(identifier)
                    ):
                        continue
                    scenes.append(nearby)
                    blocks.append(
                        {
                            "scene_id": identifier,
                            "episode_id": nearby.episode_id,
                            "start": nearby.start,
                            "end": nearby.end,
                            "timestamp_basis": nearby.timestamp_basis,
                            "missing_terms": [],
                            "role": "adjacent episode timeline context; not an independent query match",
                        }
                    )
                    response["evidence"].extend(self._select_evidence(nearby, query, None)[:3])
                response["warnings"].append(
                    "Timeline context follows episode timestamps, not necessarily story chronology."
                )
            except SearchyError:
                response["warnings"].append("Adjacent timeline evidence is unavailable.")
        # The same evidence selection drives both the model context and the explorer.
        identifiers = []
        for item in response["evidence"]:
            parts = item["evidence_id"].rsplit(":", 2)
            if len(parts) == 3 and parts[1] in {"observation", "dialogue"}:
                identifiers.append(stable_id(f"{parts[1]}:{parts[0]}:{parts[2]}"))
        if self.graph is not None:
            try:
                response["graph"] = (
                    GraphExplorer(self.graph, self.metadata)
                    .explore(
                        GraphRequest(
                            scene_ids=[s.scene_id for s in scenes],
                            collection_id=collection_id,
                            evidence_ids=identifiers,
                            max_nodes=300,
                            max_edges=500,
                        )
                    )
                    .model_dump()
                )
                response["retrieval"]["graph_used"] = True
            except SearchyError:
                response["warnings"].append(
                    "Graph expansion is unavailable; this answer uses scene evidence only."
                )
        if any(not item["verified"] for item in response["evidence"]):
            response["warnings"].append(
                "Some evidence comes from unverified machine captions or unattributed subtitles."
            )
        if any("infer" in item["timestamp_basis"] for item in blocks):
            response["warnings"].append("Episode timestamps are inferred from the original chunks.")
        missing = sorted({m for b in blocks for m in b["missing_terms"]})
        if missing:
            response["warnings"].append(
                "Not every requested detail is supported: " + ", ".join(missing)
            )
        response["constraints"] = [
            {
                "label": "All requested details in one scene",
                "supported": any(not b["missing_terms"] and "role" not in b for b in blocks),
                "detail": "Check the supporting evidence and its time interval.",
            }
        ]
        graph = response["graph"]

        def selected_graph():
            selected_ids = set()
            for item in response["evidence"]:
                parts = item["evidence_id"].rsplit(":", 2)
                if len(parts) == 3:
                    kind = "Observation" if parts[1] == "observation" else "Dialogue"
                    selected_ids.add(f"{kind}:" + stable_id(f"{parts[1]}:{parts[0]}:{parts[2]}"))
            details = [edge for edge in graph["edges"] if edge["source"] in selected_ids]
            entity_ids = {e["target"] for e in details}
            edges = [
                e
                for e in graph["edges"]
                if e["type"] == "PART_OF"
                or e["source"] in selected_ids
                or e["target"] in selected_ids
                or (
                    e["type"] in {"APPEARS_IN", "CONTAINS", "OCCURS_AT"}
                    and (e["source"] in entity_ids or e["target"] in entity_ids)
                )
            ]
            node_ids = {n for e in edges for n in (e["source"], e["target"])}
            nodes = [n for n in graph["nodes"] if n["id"] in node_ids or n["type"] == "Scene"]
            return {**graph, "nodes": nodes, "edges": edges}

        def compact_graph(selected):
            return {
                "nodes": [
                    {
                        "id": n["id"],
                        "type": n["type"],
                        "label": n["label"][:220],
                        "scene_ids": n["scene_ids"],
                        "properties": {
                            k: v
                            for k, v in n["properties"].items()
                            if k
                            in {
                                "kind",
                                "subject",
                                "subject_id",
                                "character_id",
                                "speaker_id",
                                "start",
                                "end",
                                "verified",
                                "confidence",
                            }
                        },
                    }
                    for n in selected["nodes"]
                ],
                "edges": [
                    {k: e[k] for k in ("source", "target", "type", "scene_ids")}
                    for e in selected["edges"]
                ],
            }

        context = {
            "scenes": blocks,
            "evidence": response["evidence"],
            "graph": compact_graph(selected_graph()),
            "limitations": response["warnings"],
        }
        while len(json.dumps(context)) > MAX_CONTEXT_CHARS and len(response["evidence"]) > 1:
            response["evidence"].pop()
            context["graph"] = compact_graph(selected_graph())
        response["graph"] = selected_graph()
        if len(json.dumps(context)) > MAX_CONTEXT_CHARS:
            raise SearchyError(
                "The selected evidence exceeds the answer context budget; select fewer scenes", 422
            )
        response["retrieval"]["context_characters"] = len(json.dumps(context))
        return response, context, scenes

    def _select_evidence(self, scene, query, character_ids):
        evidence = self._evidence(scene, character_ids, query)
        terms = normalized_terms(query)
        evidence.sort(
            key=lambda e: (len(terms & normalized_terms(e["text"])), e["verified"]), reverse=True
        )
        plan = understand(query, [])
        if plan.narrative or plan.temporal or plan.dialogue_intent:
            descriptions = [e for e in evidence if e["kind"] == "description"][:1]
            dialogue = [e for e in evidence if e["kind"] == "dialogue"][:3]
            other = [e for e in evidence if e["kind"] not in {"description", "dialogue"}]
            return (descriptions + dialogue + other)[:5]
        return evidence[:5]

    async def stream(
        self,
        query: str,
        scene_ids: list[str],
        collection_id=None,
        character_ids=None,
        search_id=None,
    ):
        sessions = SearchSessions(self.metadata) if search_id else None
        if sessions:
            saved = await anyio.to_thread.run_sync(sessions.get, search_id)
            req = saved["request"]
            ranked = [s["scene_id"] for s in saved["response"]["results"]]
            if (
                req["query"] != query
                or req.get("collection_id") != collection_id
                or req.get("character_ids", []) != (character_ids or [])
                or scene_ids != ranked[:12]
            ):
                raise InvalidInput("The answer request does not match its search session")
            if saved["answer"] and saved["answer"]["status"] == "generated":
                yield "answer", saved["answer"]
                return
        response, context, scenes = await anyio.to_thread.run_sync(
            self._prepare, query, scene_ids, collection_id, character_ids
        )
        response["search_id"] = search_id
        if not context:
            yield "answer", response
            return
        evidence = {e["evidence_id"]: e for e in response["evidence"]}
        plan = understand(query, self.search.requested_characters(query, collection_id))
        prompt = build_prompt(
            query,
            {
                "primary_type": plan.primary_type,
                "types": plan.types,
                "characters": plan.characters,
                "temporal": plan.temporal,
                "narrative": plan.narrative,
            },
            context,
        )
        try:
            yield "status", {"state": "generating"}
            async for claim in self.provider.stream(prompt):
                selected = self._supported_sources(claim, evidence)
                if not selected:
                    response["warnings"].append("An unsupported AI statement was omitted.")
                    continue
                if any(e["scene_id"] not in claim.scene_ids for e in selected):
                    continue
                if not any(e["verified"] for e in selected) and not re.search(
                    r"caption|description|indexed|unverified|suggest|uncertain|transcript",
                    claim.text,
                    re.I,
                ):
                    claim = claim.model_copy(
                        update={"text": "According to the indexed evidence, " + claim.text}
                    )
                yield "status", {"state": "verifying"}
                if not await self.provider.verify(
                    claim, selected, self._claim_graph(claim, context["graph"])
                ):
                    response["warnings"].append(
                        "An AI statement did not pass evidence verification and was omitted."
                    )
                    continue
                record = {
                    "text": claim.text,
                    "scene_ids": list(dict.fromkeys(claim.scene_ids)),
                    "evidence_ids": [s.evidence_id for s in claim.support],
                }
                response["claims"].append(record)
                used = list(dict.fromkeys(s for c in response["claims"] for s in c["scene_ids"]))
                response["citations"] = self._citations(scenes, used, evidence, response["claims"])
                response["answer"] = " ".join(c["text"] for c in response["claims"])
                response["markdown"] = response["answer"]
                response["status"] = "generated"
                response["provider"], response["model"] = (
                    self.settings.llm_provider,
                    self.settings.llm_model_id,
                )
                yield (
                    "delta",
                    {
                        "text": response["answer"],
                        "claims": response["claims"],
                        "citations": response["citations"],
                    },
                )
        except SearchyError as exc:
            response["warnings"].append(str(exc))
            if not response["claims"]:
                response["status"] = "unavailable"
        response["warnings"] = list(dict.fromkeys(response["warnings"]))
        if sessions and response["status"] == "generated":
            await anyio.to_thread.run_sync(sessions.save_answer, search_id, response)
        yield "answer", response

    @staticmethod
    def _claim_graph(claim, graph):
        identifiers = set()
        for support in claim.support:
            parts = support.evidence_id.rsplit(":", 2)
            if len(parts) == 3:
                kind = "Observation" if parts[1] == "observation" else "Dialogue"
                identifiers.add(f"{kind}:" + stable_id(f"{parts[1]}:{parts[0]}:{parts[2]}"))
        edges = [
            e
            for e in graph["edges"]
            if (e["source"] in identifiers or e["target"] in identifiers)
            and set(e["scene_ids"]) & set(claim.scene_ids)
        ]
        nodes = {i for e in edges for i in (e["source"], e["target"])}
        return {"nodes": [n for n in graph["nodes"] if n["id"] in nodes], "edges": edges}

    @staticmethod
    def _supported_sources(claim, evidence):
        if re.search(
            r"[<>\[\]`]|\*\*|#{1,6}\s|(?:https?|javascript|data):|\b\d{1,2}:\d{2}\b",
            claim.text,
            re.I,
        ):
            return []
        selected = []
        for support in claim.support:
            item = evidence.get(support.evidence_id)
            if item is None or item["scene_id"] not in claim.scene_ids:
                return []
            if " ".join(support.quote.casefold().split()) not in " ".join(
                item["text"].casefold().split()
            ):
                return []
            selected.append(item)
        if {e["scene_id"] for e in selected} != set(claim.scene_ids):
            return []
        return selected

    @staticmethod
    def _citations(scenes, used, evidence, claims):
        citations = []
        for scene in scenes:
            if scene.scene_id not in used:
                continue
            pieces = [
                evidence[i]
                for c in claims
                for i in c["evidence_ids"]
                if evidence[i]["scene_id"] == scene.scene_id
            ]
            times = [e["start"] for e in pieces if e["start"] is not None]
            start = min(times) if times else scene.start
            if start is not None and scene.start is not None:
                start = max(scene.start, min(start, scene.end if scene.end is not None else start))
            citations.append(
                {
                    "scene_id": scene.scene_id,
                    "label": f"Scene {len(citations) + 1}",
                    "episode_id": scene.episode_id,
                    "start": start,
                    "end": scene.end,
                    "timestamp_basis": scene.timestamp_basis,
                    "available": bool(scene.media and Path(scene.media.path).is_file()),
                    "url": f"/scenes/{scene.scene_id}",
                    "evidence_ids": list(dict.fromkeys(e["evidence_id"] for e in pieces)),
                }
            )
        return citations

    @staticmethod
    def _constraints(
        query: str,
        scene,
        requested: list[str],
        character_ids: list[str] | None = None,
    ) -> list[str] | None:
        if character_ids and not set(character_ids) <= set(scene.character_ids):
            return None
        if not all(
            any(character_matches(actual, name) for actual in scene.characters)
            for name in requested
        ):
            return None
        plan = understand(query, requested)
        if not clothing_matches(clothing_query(query), scene, requested, character_ids):
            return None
        content = plan.content_tokens
        target = content - {"dialogue", "quote"}
        if plan.dialogue_intent and not dialogue_matches(
            " ".join(line.text for line in scene.dialogue), list(plan.quoted), target
        ):
            return None
        observed = normalized_terms(scene.search_text())
        missing = sorted(term for term in content if not normalized_terms(term) <= observed)
        action_terms = plan.action_terms
        if (
            requested
            and action_terms
            and not plan.dialogue_intent
            and not all(
                any(
                    observation.kind in {"action", "interaction"}
                    and observation.subject
                    and character_matches(observation.subject, name)
                    and action_terms <= normalized_terms(observation.value)
                    for observation in scene.observations
                )
                for name in requested
            )
        ):
            missing.append("character action association")
        if (
            plan.dialogue_intent
            and requested
            and not all(
                speaker_matches(scene, name, list(plan.quoted), target) for name in requested
            )
        ):
            missing.append("character dialogue association")
        if (
            character_ids
            and action_terms
            and not plan.dialogue_intent
            and not all(
                any(
                    observation.kind in {"action", "interaction"}
                    and identity_key(scene, observation.subject, observation.subject_id)
                    == identifier
                    and action_terms <= normalized_terms(observation.value)
                    for observation in scene.observations
                )
                for identifier in character_ids
            )
        ):
            missing.append("character action association")
        if (
            character_ids
            and plan.dialogue_intent
            and not all(
                speaker_matches(scene, "", list(plan.quoted), target, identifier)
                for identifier in character_ids
            )
        ):
            missing.append("character dialogue association")
        if re.search(r"\b(while|simultaneously)\b|at the same time", query, re.I) and plan.clothing:
            outfits = [
                o
                for o in scene.observations
                if o.kind == "clothing"
                and normalized_terms(o.value) & normalized_terms(" ".join(plan.clothing))
            ]
            actions = [
                o
                for o in scene.observations
                if o.kind in {"action", "interaction"}
                and plan.action_terms
                and plan.action_terms <= normalized_terms(o.value)
            ]
            timed_outfits = [o for o in outfits if o.start is not None and o.end is not None]
            timed_actions = [o for o in actions if o.start is not None and o.end is not None]
            if (
                outfits
                and actions
                and len(timed_outfits) == len(outfits)
                and len(timed_actions) == len(actions)
            ):
                if not any(
                    max(a.start, b.start) < min(a.end, b.end)
                    for a in timed_outfits
                    for b in timed_actions
                ):
                    return None
            else:
                missing.append("simultaneous timing unverified")
        return list(dict.fromkeys(missing))

    @staticmethod
    def _evidence(scene, character_ids: list[str] | None = None, query: str = "") -> list[dict]:
        items = []
        selected = set(character_ids or [])
        if scene.description.strip():
            items.append(
                {
                    "evidence_id": f"{scene.scene_id}:description",
                    "scene_id": scene.scene_id,
                    "kind": "description",
                    "text": (
                        "Scene context; character ownership is unassigned: " if selected else ""
                    )
                    + clean_caption(scene.description)[:MAX_DESCRIPTION],
                    "verified": False,
                    "confidence": None,
                    "start": scene.start,
                    "end": scene.end,
                }
            )
        observations = [
            (
                index,
                observation,
                identity_key(scene, observation.value, observation.character_id)
                if observation.kind == "character"
                else identity_key(scene, observation.subject, observation.subject_id),
            )
            for index, observation in enumerate(scene.observations)
            if not selected
            or not ({observation.character_id, observation.subject_id} - {None}) - selected
        ]
        observations.sort(
            key=lambda item: (
                bool(selected) and item[2] not in selected,
                -len(
                    normalized_terms(query)
                    & normalized_terms(item[1].value + " " + item[1].evidence)
                ),
                not item[1].provenance.verified,
                item[0],
            )
        )
        for index, observation, identifier in observations[:MAX_EVIDENCE_PER_SCENE]:
            explicit = (
                observation.character_id
                if observation.kind.value == "character"
                else observation.subject_id
            )
            identity = f"character_id: {explicit or 'unassigned'}; "
            if not explicit and selected and identifier in selected:
                identity += f"Imported name label ID: {identifier}; "
            subject = f"{observation.subject}: " if observation.subject else ""
            items.append(
                {
                    "evidence_id": f"{scene.scene_id}:observation:{index}",
                    "scene_id": scene.scene_id,
                    "kind": observation.kind.value,
                    "text": f"{identity}{subject}{observation.value}"[:400],
                    "verified": observation.provenance.verified,
                    "confidence": observation.provenance.confidence,
                    "start": observation.start,
                    "end": observation.end,
                }
            )
        dialogue = [
            (index, line, identity_key(scene, line.speaker, line.speaker_id))
            for index, line in enumerate(scene.dialogue)
            if not selected or not line.speaker_id or line.speaker_id in selected
        ]
        dialogue.sort(
            key=lambda item: (
                bool(selected) and item[2] not in selected,
                -len(normalized_terms(query) & normalized_terms(item[1].text)),
                not bool(item[1].provenance and item[1].provenance.verified),
                item[0],
            )
        )
        for index, line, identifier in dialogue[:MAX_EVIDENCE_PER_SCENE]:
            identity = f"speaker_id: {line.speaker_id or 'unassigned'}; "
            if not line.speaker_id and selected and identifier in selected:
                identity += f"Imported name label ID: {identifier}; "
            speaker = f"{line.speaker}: " if line.speaker else ""
            items.append(
                {
                    "evidence_id": f"{scene.scene_id}:dialogue:{index}",
                    "scene_id": scene.scene_id,
                    "kind": "dialogue",
                    "text": f"{identity}{speaker}{line.text}"[:400],
                    "verified": bool(line.provenance and line.provenance.verified),
                    "confidence": line.provenance.confidence if line.provenance else None,
                    "start": line.start,
                    "end": line.end,
                }
            )
        return items


def clean_caption(text: str) -> str:
    return " ".join(re.sub(r"#{1,6}\s*|\*\*|__|`{1,3}", "", text).split())
