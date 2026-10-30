import re
from pathlib import Path

import httpx

from searchy.core.config import Settings
from searchy.core.errors import InvalidInput, SearchyError
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

MAX_CITED_SCENES = 4
MAX_CONTEXT_SCENES = 12
MAX_DESCRIPTION = 700
MAX_EVIDENCE_PER_SCENE = 6


class AnswerService:
    def __init__(
        self,
        settings: Settings,
        metadata: MetadataStore,
        search,
        graph=None,
        transport: httpx.BaseTransport | None = None,
    ):
        self.settings = settings
        self.metadata = metadata
        self.search = search
        self.graph = graph
        self.provider = AnswerProvider(settings, transport)

    def answer(
        self,
        query: str,
        scene_ids: list[str],
        collection_id: str | None = None,
        character_ids: list[str] | None = None,
    ) -> dict:
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
            "query_type": None,
        }
        empty_reason = self._empty_reason(query, scene_ids)
        if empty_reason:
            response["warnings"].append(empty_reason)
            response["query_type"] = understand(query, []).primary_type
            return response

        scenes = []
        for scene_id in scene_ids[:MAX_CONTEXT_SCENES]:
            scene = self.metadata.get_scene(scene_id)
            if scene is None:
                raise SearchyError("A requested scene was not found", 404)
            if collection_id is not None and scene.collection_id != collection_id:
                raise InvalidInput("Requested scenes must belong to the selected collection")
            if not self.metadata.is_indexed(scene_id):
                raise SearchyError("A requested scene is not currently indexed", 409)
            scenes.append(scene)

        requested = self.search.requested_characters(query, collection_id)
        plan = understand(query, requested)
        response["query_type"] = plan.primary_type
        dropped = 0
        context = []
        for scene in scenes:
            missing = self._constraints(query, scene, requested, character_ids)
            if missing is None:
                dropped += 1
                continue
            evidence = self._evidence(scene, character_ids)
            if not evidence:
                continue
            context.append(
                {
                    "scene_id": scene.scene_id,
                    "timestamp_basis": scene.timestamp_basis,
                    "missing_terms": missing,
                    "selected_character_ids": character_ids or [],
                    "playback_available": bool(scene.media and Path(scene.media.path).is_file()),
                }
            )
            response["evidence"].extend(evidence)
        if dropped:
            response["warnings"].append(
                "Some retrieved scenes do not support the query's explicit character, outfit or "
                "dialogue constraints and were left out of the explanation"
            )
        if not response["evidence"]:
            response["warnings"].append(
                "The retrieved scenes do not contain enough evidence to answer this question"
            )
            return response

        relationships = self._graph_context([item["scene_id"] for item in context], collection_id)
        response["relationships"] = relationships
        response["constraints"] = self._constraint_report(plan, context, requested, character_ids)
        if any(not item["verified"] for item in response["evidence"]):
            response["warnings"].append(
                "Scene descriptions are unverified machine captions, so the answer describes "
                "what the indexed evidence says rather than confirmed frames"
            )
        if any(item["missing_terms"] for item in context):
            response["warnings"].append(
                "The indexed evidence does not verify every detail of this query"
            )
        if any("infer" in item["timestamp_basis"].lower() for item in context):
            response["warnings"].append(
                "Timestamps are inferred from the original 60-second chunks"
            )

        try:
            generated = self.provider.generate(
                build_prompt(query, self._plan_payload(plan), context, response["evidence"])
            )
            answer, used = self._verify(generated, context)
            if not answer:
                response["warnings"].append(
                    "The AI provider found insufficient evidence to answer this question"
                )
                return response
            response.update(
                status="generated",
                answer=answer,
                markdown=answer,
                claims=[
                    {
                        "text": answer,
                        "scene_ids": used,
                        "evidence_ids": [
                            item["evidence_id"]
                            for item in response["evidence"]
                            if item["scene_id"] in used
                        ][:MAX_CITED_SCENES],
                    }
                ],
                citations=self._citations(scenes, used),
                provider=self.settings.llm_provider,
                model=self.settings.llm_model_id,
            )
        except SearchyError as exc:
            response["status"] = "unavailable"
            response["warnings"].append(str(exc))
        response["warnings"] = list(dict.fromkeys(response["warnings"]))
        return response

    @staticmethod
    def _empty_reason(query: str, scene_ids: list[str]) -> str | None:
        if scene_ids:
            return None
        return "No scenes were retrieved, so there is nothing to explain"

    @staticmethod
    def _plan_payload(plan) -> dict:
        return {
            "primary_type": plan.primary_type,
            "types": list(plan.types),
            "constraints": {
                "characters": list(plan.characters),
                "clothing": list(plan.clothing),
                "dialogue": list(plan.quoted),
                "actions": sorted(plan.action_terms),
                "keywords": sorted(plan.content_tokens),
            },
            "notes": list(plan.missing_constraints),
        }

    @staticmethod
    def _constraint_report(plan, context: list[dict], requested, character_ids) -> list[dict]:
        """Report per-constraint support so the UI can show what is proven and what is not."""
        missing = {term for item in context for term in item["missing_terms"]}
        report = []

        def add(label: str, supported: bool, detail: str):
            report.append(
                {
                    "label": label,
                    "supported": supported,
                    "detail": detail
                    if supported
                    else "not confirmed by the indexed evidence",
                }
            )

        if requested:
            add(
                f"Character {' + '.join(requested)} appears",
                True,
                f"every returned scene lists {' + '.join(requested)}",
            )
        if character_ids:
            add(
                "Registered identity filter",
                True,
                f"{len(character_ids)} character identifier(s) matched",
            )
        if plan.clothing:
            add(
                f"Clothing: {' / '.join(plan.clothing)}",
                "clothing" not in missing,
                "the outfit is named in the scene observations",
            )
        if plan.quoted:
            add(
                f"Dialogue: \"{plan.quoted[0]}\"",
                "dialogue" not in missing,
                "the line appears in the scene transcript",
            )
        if plan.action_terms:
            add(
                f"Action: {' / '.join(sorted(plan.action_terms))}",
                "character action association" not in missing,
                "an observation attributes the action to the character",
            )
        if "character dialogue association" in missing:
            add(
                "Speaker identity",
                False,
                "the matching speech has no supported speaker identity",
            )
        if not report:
            add(
                "Keyword match",
                True,
                f"{len(context)} scene(s) contain the query terms",
            )
        return report

    def _graph_context(self, scene_ids: list[str], collection_id: str | None) -> list[dict]:
        if self.graph is None or not scene_ids:
            return []
        try:
            found = self.graph.context(scene_ids, collection_id)
        except SearchyError:
            return []
        rows = []
        for scene_id, item in found.items():
            rows.append({"scene_id": scene_id, **item})
        return rows

    @staticmethod
    def _verify(generated, context: list[dict]) -> tuple[str, list[str]]:
        """Keep only an answer whose scene references really exist and match the prose.

        Returns the answer plus the ordered scene ids it may cite. Raises when the
        provider produced something unusable rather than silently publishing it.
        """
        accepted = [item["scene_id"] for item in context]
        text = " ".join(generated.answer.split())
        cited = [scene_id for scene_id in generated.scene_ids if scene_id in accepted]
        if not text or len(text) > 900:
            return "", []
        if re.search(
            r"[<>\[\]]|(?:https?|javascript|data):|\b\d{1,2}:\d{2}\b|!\[|#{1,6}\s", text, re.I
        ):
            raise SearchyError(
                "AI explanations are unavailable: provider returned links or formatting"
            )
        if not cited:
            return "", []
        cited = list(dict.fromkeys(cited))[:MAX_CITED_SCENES]
        return text, cited

    @staticmethod
    def _citations(scenes, used: list[str]) -> list[dict]:
        citations = []
        for scene in scenes:
            if scene.scene_id not in used:
                continue
            citations.append(
                {
                    "scene_id": scene.scene_id,
                    "label": f"Scene {len(citations) + 1}",
                    "episode_id": scene.episode_id,
                    "start": scene.start,
                    "end": scene.end,
                    "timestamp_basis": scene.timestamp_basis,
                    "available": bool(scene.media and Path(scene.media.path).is_file()),
                    "url": f"/scenes/{scene.scene_id}",
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
            and not all(speaker_matches(scene, name, list(plan.quoted), target) for name in requested)
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
        return list(dict.fromkeys(missing))

    @staticmethod
    def _evidence(scene, character_ids: list[str] | None = None) -> list[dict]:
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


_CAPTION_NOISE = re.compile(r"#{1,6}\s*|\*\*|__|`{1,3}")


def clean_caption(text: str) -> str:
    """Strip caption markdown so the model reads plain sentences, not headings."""
    flattened = _CAPTION_NOISE.sub("", text)
    lines = [line.strip(" -*\t") for line in flattened.splitlines()]
    return " ".join(line for line in lines if line)


__all__ = ["AnswerService", "clean_caption"]
