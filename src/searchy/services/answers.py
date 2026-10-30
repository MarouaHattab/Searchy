import re
from pathlib import Path
from urllib.parse import quote

import httpx

from searchy.core.config import Settings
from searchy.core.errors import InvalidInput, SearchyError
from searchy.domain import Scene
from searchy.models.answers import AnswerProvider
from searchy.retrieval.search import (
    ACTION_WORDS,
    STOP_WORDS,
    character_matches,
    clothing_matches,
    dialogue_matches,
    identity_key,
    normalized_terms,
    speaker_matches,
    tokens,
)
from searchy.storage.metadata import MetadataStore


class AnswerService:
    def __init__(
        self,
        settings: Settings,
        metadata: MetadataStore,
        search,
        transport: httpx.BaseTransport | None = None,
    ):
        self.settings = settings
        self.metadata = metadata
        self.search = search
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
            "markdown": "",
            "claims": [],
            "citations": [],
            "evidence": [],
            "warnings": [],
            "provider": None,
            "model": None,
        }
        if not scene_ids:
            response["warnings"].append(
                "No retrieved scenes were supplied; no AI explanation was generated"
            )
            return response
        scenes = []
        for scene_id in scene_ids:
            scene = self.metadata.get_scene(scene_id)
            if scene is None:
                raise SearchyError("A requested scene was not found", 404)
            if collection_id is not None and scene.collection_id != collection_id:
                raise InvalidInput("Requested scenes must belong to the selected collection")
            if not self.metadata.is_indexed(scene_id):
                raise SearchyError("A requested scene is not currently indexed", 409)
            scenes.append(scene)
        requested = self.search.requested_characters(query, collection_id)
        context = []
        for scene in scenes:
            constraints = self._constraints(query, scene, requested, character_ids)
            if constraints is None:
                response["warnings"].append(
                    "Some supplied scenes do not support the query's explicit character, outfit or dialogue constraints"
                )
                continue
            evidence = self._evidence(scene, character_ids)
            if not evidence:
                continue
            context.append(
                {
                    "scene_id": scene.scene_id,
                    "timestamp_basis": scene.timestamp_basis,
                    "missing_terms": constraints,
                    "selected_character_ids": character_ids or [],
                    "playback_available": bool(scene.media and Path(scene.media.path).is_file()),
                }
            )
            response["evidence"].extend(evidence)
        if not response["evidence"]:
            response["warnings"].append(
                "The supplied indexed scenes do not contain sufficient supporting evidence"
            )
            return response
        if any(not item["verified"] for item in response["evidence"]):
            response["warnings"].append(
                "Some indexed evidence is unverified; an AI explanation does not verify its accuracy"
            )
        if any("inferred" in item["timestamp_basis"].lower() for item in context):
            response["warnings"].append("Some scene timestamps are inferred from imported chunks")
        if any(item["missing_terms"] for item in context):
            response["warnings"].append(
                "The indexed evidence does not verify every query constraint"
            )
        try:
            generated = self.provider.generate(query, context, response["evidence"])
            allowed = {item["evidence_id"]: item for item in response["evidence"]}
            accepted_ids = {item["scene_id"] for item in context}
            claims = []
            for claim in generated.claims:
                text = " ".join(claim.text.split())
                cited_scenes = set(claim.scene_ids)
                cited_evidence = set(claim.evidence_ids)
                if (
                    not text
                    or re.search(
                        r"[<>\[\]]|(?:https?|javascript|data):|\b\d{1,2}:\d{2}\b", text, re.I
                    )
                    or not cited_scenes <= accepted_ids
                    or not cited_evidence <= allowed.keys()
                    or {allowed[key]["scene_id"] for key in cited_evidence} != cited_scenes
                ):
                    raise SearchyError(
                        "AI explanations are unavailable: provider returned unsupported citations or formatting"
                    )
                source_terms = tokens(" ".join(allowed[key]["text"] for key in cited_evidence))
                if any(
                    term.casefold() not in source_terms
                    for term in re.findall(r"\b\w*\d\w*\b", text)
                ):
                    raise SearchyError(
                        "AI explanations are unavailable: provider returned unsupported numeric details"
                    )
                if any(not allowed[key]["verified"] for key in cited_evidence) and not re.search(
                    r"\b(suggests?|unverified|uncertain)\b", text, re.I
                ):
                    text = f"Indexed evidence suggests: {text}"
                    if len(text) > 500:
                        raise SearchyError(
                            "AI explanations are unavailable: provider explanation exceeded its length limit"
                        )
                claims.append(
                    {
                        "text": text,
                        "scene_ids": list(dict.fromkeys(claim.scene_ids)),
                        "evidence_ids": list(dict.fromkeys(claim.evidence_ids)),
                    }
                )
            if not claims:
                response["warnings"].append(
                    "The AI provider found insufficient evidence for an explanation"
                )
                return response
            used = {scene_id for claim in claims for scene_id in claim["scene_ids"]}
            citations = []
            for scene in scenes:
                if scene.scene_id in used:
                    citations.append(
                        {
                            "scene_id": scene.scene_id,
                            "label": f"Scene {len(citations) + 1}",
                            "start": scene.start,
                            "end": scene.end,
                            "timestamp_basis": scene.timestamp_basis,
                            "available": bool(scene.media and Path(scene.media.path).is_file()),
                            "url": f"/scenes/{quote(scene.scene_id, safe='')}",
                        }
                    )
            by_id = {item["scene_id"]: item for item in citations}
            markdown = "\n\n".join(
                claim["text"]
                + " "
                + " ".join(
                    f"[{by_id[scene_id]['label']}]({by_id[scene_id]['url']})"
                    for scene_id in claim["scene_ids"]
                )
                for claim in claims
            )
            response.update(
                status="generated",
                markdown=markdown,
                claims=claims,
                citations=citations,
                provider=self.settings.llm_provider,
                model=self.settings.llm_model_id,
            )
        except SearchyError as exc:
            response["status"] = "unavailable"
            response["warnings"].append(str(exc))
        response["warnings"] = list(dict.fromkeys(response["warnings"]))
        return response

    @staticmethod
    def _constraints(
        query: str,
        scene: Scene,
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
        quoted = re.findall(r'["“](.+?)["”]', query)
        dialogue_intent = bool(
            quoted or re.search(r"\b(says?|saying|dialogue|quote)\b", query, re.I)
        )
        clothing_query = re.sub(r'["“].+?["”]', "", query)
        if dialogue_intent and not re.search(
            r"\b(wearing|wears|outfits?|clothes|clothing)\b", clothing_query, re.I
        ):
            clothing_query = ""
        if not clothing_matches(clothing_query, scene, requested, character_ids):
            return None
        content = tokens(query) - STOP_WORDS - {word for name in requested for word in tokens(name)}
        target = content - {"dialogue", "quote"}
        if dialogue_intent and not dialogue_matches(
            " ".join(line.text for line in scene.dialogue), quoted, target
        ):
            return None
        observed = normalized_terms(scene.search_text())
        missing = sorted(term for term in content if not normalized_terms(term) <= observed)
        action_terms = normalized_terms(" ".join(content)) & ACTION_WORDS
        if (
            requested
            and action_terms
            and not dialogue_intent
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
            dialogue_intent
            and requested
            and not all(speaker_matches(scene, name, quoted, target) for name in requested)
        ):
            missing.append("character dialogue association")
        if (
            character_ids
            and action_terms
            and not dialogue_intent
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
            and dialogue_intent
            and not all(
                speaker_matches(scene, "", quoted, target, identifier)
                for identifier in character_ids
            )
        ):
            missing.append("character dialogue association")
        return list(dict.fromkeys(missing))

    @staticmethod
    def _evidence(scene: Scene, character_ids: list[str] | None = None) -> list[dict]:
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
                    + scene.description[:1200],
                    "verified": not selected
                    and bool(scene.provenance)
                    and all(item.verified for item in scene.provenance),
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
        for index, observation, identifier in observations[:8]:
            identity_field = "character_id" if observation.kind == "character" else "subject_id"
            explicit = (
                observation.character_id
                if observation.kind == "character"
                else observation.subject_id
            )
            identity_text = f"{identity_field}: {explicit or 'unassigned'}; "
            if not explicit and identifier in selected:
                identity_text += f"Imported name label ID: {identifier}; "
            items.append(
                {
                    "evidence_id": f"{scene.scene_id}:observation:{index}",
                    "scene_id": scene.scene_id,
                    "kind": observation.kind.value,
                    "text": f"{identity_text}Subject label: {observation.subject or 'unassigned'}; value: {observation.value}; evidence: {observation.evidence}"[
                        :600
                    ],
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
        for index, line, identifier in dialogue[:8]:
            identity_text = f"speaker_id: {line.speaker_id or 'unassigned'}; "
            if not line.speaker_id and identifier in selected:
                identity_text += f"Imported name label ID: {identifier}; "
            items.append(
                {
                    "evidence_id": f"{scene.scene_id}:dialogue:{index}",
                    "scene_id": scene.scene_id,
                    "kind": "dialogue",
                    "text": f"{identity_text}Speaker label: {line.speaker or 'unidentified'}; dialogue: {line.text}"[
                        :400
                    ],
                    "verified": bool(line.provenance and line.provenance.verified),
                    "confidence": line.provenance.confidence if line.provenance else None,
                    "start": line.start,
                    "end": line.end,
                }
            )
        return items
