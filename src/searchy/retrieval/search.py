import re
from collections import defaultdict
from pathlib import Path

from searchy.core.config import Settings
from searchy.core.errors import InvalidInput, SearchyError
from searchy.domain import Candidate, Scene, stable_id
from searchy.storage.characters import CharacterStore
from searchy.storage.metadata import MetadataStore

STOP_WORDS = set(
    "find show scene scenes where someone somebody wearing wears is are a an the me in on of to with and or says say saying they their outfit outfits clothes clothing please video videos that he she you i it your this for at as be by from".split()
)
GARMENTS = set(
    "shirt pants trousers dress jacket jeans skirt sweater coat suit tie vest blouse shorts shoes top blazer cardigan overalls hoodie scarf hat apron robe boots".split()
)
CLOTHING_MODIFIERS = set(
    "leather denim red blue green black white yellow pink orange purple grey gray brown dark light colored striped patterned floral sleeveless silk cotton wool velvet".split()
)
ACTION_WORDS = set(
    "talk argue drive kiss hug eat drink cook dance run walk sit stand play laugh smile cry fight hold read write enter leave gesture look listen discuss shout yell speak sing sleep chase smoke meet flirt bake point interact".split()
)
NORMALIZED_WORDS = {
    **{word + "s": word for word in GARMENTS if not word.endswith("s")},
    **{word + "s": word for word in ACTION_WORDS},
    **{(word[:-1] if word.endswith("e") else word) + "ing": word for word in ACTION_WORDS},
    "dresses": "dress",
    "grey": "gray",
    "talking": "talk",
    "talks": "talk",
    "conversation": "talk",
    "conversing": "talk",
    "chatting": "talk",
    "driving": "drive",
    "drives": "drive",
    "drove": "drive",
    "arguing": "argue",
    "argues": "argue",
    "argued": "argue",
    "argument": "argue",
    "interaction": "interact",
    "running": "run",
    "sitting": "sit",
    "hugging": "hug",
}
NEGATIONS = {"not", "never", "dont", "doesnt", "didnt", "cant", "cannot", "wont", "wouldnt"}


def words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower().replace("’", "'").replace("'", ""))


def tokens(text: str) -> set[str]:
    return set(words(text))


def normalized_terms(text: str) -> set[str]:
    return {NORMALIZED_WORDS.get(word, word) for word in words(text)}


def character_matches(actual: str, requested: str) -> bool:
    actual = " ".join(actual.casefold().split())
    requested = " ".join(requested.casefold().split())
    return actual == requested or actual.startswith(requested + " ")


def dialogue_matches(text: str, quoted: list[str], target: set[str]) -> bool:
    if quoted:
        transcript_phrase = " " + " ".join(words(text)) + " "
        return all(" " + " ".join(words(phrase)) + " " in transcript_phrase for phrase in quoted)
    spoken = tokens(text)
    return bool(
        target and not (target & NEGATIONS) - spoken and len(target & spoken) / len(target) >= 0.75
    )


def identity_key(scene: Scene, name: str | None, explicit: str | None) -> str | None:
    return explicit or (
        stable_id(f"character:{scene.collection_id}:{' '.join(name.casefold().split())}")
        if name
        else None
    )


def speaker_matches(
    scene: Scene, name: str, quoted: list[str], target: set[str], character_id: str | None = None
) -> bool:
    runs = []
    current = []
    for line in scene.dialogue:
        if (
            identity_key(scene, line.speaker, line.speaker_id) == character_id
            if character_id
            else line.speaker and character_matches(line.speaker, name)
        ):
            current.append(line.text)
        elif current:
            runs.append(" ".join(current))
            current = []
    if current:
        runs.append(" ".join(current))
    if quoted:
        return all(
            any(dialogue_matches(run, [phrase], target) for run in runs) for phrase in quoted
        )
    return any(dialogue_matches(run, [], target) for run in runs)


def garment_phrases(text: str) -> list[set[str]]:
    phrases = []
    modifiers = set()
    for word in words(text):
        word = NORMALIZED_WORDS.get(word, word)
        if word in GARMENTS:
            phrases.append(modifiers | {word})
            modifiers = set()
        elif word in CLOTHING_MODIFIERS:
            modifiers.add(word)
        elif word not in {"and", "colored", "coloured"}:
            modifiers = set()
    return phrases


def clothing_matches(
    query: str, scene: Scene, requested: list[str], character_ids: list[str] | None = None
) -> bool:
    if len(requested) > 1:
        mentions = []
        for name in requested:
            pattern = (
                rf"\b{re.escape(name.split()[0])}(?:\s+{re.escape(' '.join(name.split()[1:]))})?\b"
                if len(name.split()) > 1
                else rf"\b{re.escape(name)}\b"
            )
            mentions.extend(
                (match.start(), match.end(), name) for match in re.finditer(pattern, query, re.I)
            )
        mentions.sort()
        clauses = []
        for index, (_, end, name) in enumerate(mentions):
            part = query[end : mentions[index + 1][0] if index + 1 < len(mentions) else len(query)]
            if garment_phrases(part) or (
                re.search(r"\bwear", part, re.I) and normalized_terms(part) & CLOTHING_MODIFIERS
            ):
                clauses.append((name, part))
                previous = index - 1
                while previous >= 0 and re.fullmatch(
                    r"\s*(?:and|&)\s*",
                    query[mentions[previous][1] : mentions[previous + 1][0]],
                    re.I,
                ):
                    clauses.append((mentions[previous][2], part))
                    previous -= 1
        if clauses:
            return all(
                clothing_matches(
                    part,
                    scene,
                    [name],
                    [
                        identifier
                        for identifier in (character_ids or [])
                        if any(
                            (
                                observation.kind == "character"
                                and character_matches(observation.value, name)
                                and identity_key(scene, observation.value, observation.character_id)
                                == identifier
                            )
                            or (
                                observation.subject
                                and character_matches(observation.subject, name)
                                and identity_key(scene, observation.subject, observation.subject_id)
                                == identifier
                            )
                            for observation in scene.observations
                        )
                    ]
                    or None,
                )
                for name, part in clauses
            )
    requirements = garment_phrases(query)
    if not requirements:
        if not re.search(r"\b(wearing|wears|outfits?|clothes|clothing)\b", query, re.IGNORECASE):
            return True
        modifiers = normalized_terms(query) & CLOTHING_MODIFIERS
        if not modifiers:
            return True
        requirements = [{modifier} for modifier in modifiers]
    by_subject = defaultdict(list)
    for index, observation in enumerate(scene.observations):
        if observation.kind != "clothing":
            continue
        subject_id = identity_key(scene, observation.subject, observation.subject_id)
        if character_ids and subject_id not in character_ids:
            continue
        if requested and (
            not observation.subject
            or not any(character_matches(observation.subject, name) for name in requested)
        ):
            continue
        subject = (
            subject_id
            if character_ids
            else observation.subject.casefold()
            if observation.subject
            else f"unassigned:{index}"
        )
        by_subject[subject].extend(garment_phrases(observation.value))
    matching_subjects = {
        subject
        for subject, phrases in by_subject.items()
        if all(any(required <= phrase for phrase in phrases) for required in requirements)
    }
    if character_ids:
        return set(character_ids) <= matching_subjects
    if requested:
        return all(
            any(character_matches(subject, name) for subject in matching_subjects)
            for name in requested
        )
    return bool(matching_subjects)


def simultaneous_timing(
    query: str,
    scene: Scene,
    requested: list[str],
    character_ids: list[str] | None,
    action_terms: set[str] | frozenset[str],
) -> str | None:
    outside_quote = re.sub(r'["“].+?["”]', "", query)
    if not re.search(
        r"\b(while|simultaneously)\b|at the same time", outside_quote, re.I
    ) or not garment_phrases(outside_quote):
        return None
    outfits = [
        o
        for o in scene.observations
        if o.kind == "clothing"
        and clothing_matches(
            outside_quote, scene.model_copy(update={"observations": [o]}), requested, character_ids
        )
    ]
    actions = [
        o
        for o in scene.observations
        if o.kind in {"action", "interaction"}
        and action_terms
        and action_terms <= normalized_terms(o.value)
        and (
            identity_key(scene, o.subject, o.subject_id) in character_ids
            if character_ids
            else not requested
            or o.subject
            and any(character_matches(o.subject, name) for name in requested)
        )
    ]
    if (
        not outfits
        or not actions
        or any(o.start is None or o.end is None for o in outfits + actions)
    ):
        return "unverified"
    if any(
        max(a.start, b.start) < min(a.end, b.end)
        or a.start == a.end
        and b.start <= a.start < b.end
        or b.start == b.end
        and a.start <= b.start < a.end
        or a.start == a.end == b.start == b.end
        for a in outfits
        for b in actions
    ):
        return "compatible"
    return "disjoint"


def playback(scene: Scene) -> dict:
    available = bool(scene.media and Path(scene.media.path).is_file())
    return dict(
        available=available,
        url=f"/api/scenes/{scene.scene_id}/media" if available else None,
        start_offset=scene.media.start_offset if available else None,
        reason=None if available else "No accessible source media is available for this scene",
    )


def scene_view(scene: Scene) -> dict:
    return {
        **scene.model_dump(exclude={"media", "frames"}),
        "characters": scene.characters,
        "character_ids": scene.character_ids,
        "playback": playback(scene),
    }


class SearchEngine:
    def __init__(self, settings: Settings, metadata: MetadataStore, graph, vectors):
        self.settings = settings
        self.metadata = metadata
        self.graph = graph
        self.vectors = vectors

    def requested_characters(self, query: str, collection_id: str | None) -> list[str]:
        known = set(self.metadata.characters(collection_id))
        if self.settings.character_reference_dir and self.settings.character_reference_dir.is_dir():
            known.update(path.stem for path in self.settings.character_reference_dir.glob("*.png"))
        known = {name.strip() for name in known if name.strip()}
        exact = {
            name
            for name in known
            if re.search(rf"\b{re.escape(name.casefold())}\b", query.casefold())
        }
        found = {
            name
            for name in exact
            if not any(name != other and character_matches(other, name) for other in exact)
        }
        aliases = defaultdict(set)
        for name in known:
            aliases[name.split()[0].casefold()].add(name)
        for alias, names in aliases.items():
            if any(name in found and len(name.split()) > 1 for name in names):
                continue
            if re.search(rf"\b{re.escape(alias)}\b", query.casefold()):
                found.add(next(iter(names)) if len(names) == 1 else sorted(names)[0].split()[0])
        return sorted(found)

    def search(
        self,
        query: str,
        limit: int = 10,
        collection_id: str | None = None,
        mode: str = "hybrid",
        characters: list[str] | None = None,
        character_ids: list[str] | None = None,
    ) -> dict:
        registered = (
            CharacterStore(self.metadata.path).list(collection_id)
            if hasattr(self.metadata, "path")
            else []
        )
        if character_ids:
            _, records, _ = self.metadata.catalog_records()
            known_ids = {
                identifier
                for scene, _ in records
                if collection_id is None or scene.collection_id == collection_id
                for identifier in scene.character_ids
            }
            known_ids.update(character["id"] for character in registered)
            if not set(character_ids) <= known_ids:
                raise InvalidInput("Character identifiers must belong to the selected collection")
        else:
            matches = defaultdict(list)
            for character in registered:
                normalized = " ".join(character["name"].casefold().split())
                if re.search(rf"\b{re.escape(normalized)}\b", query.casefold()):
                    matches[normalized].append(character)
            if any(len(values) > 1 for values in matches.values()):
                return dict(
                    query=query,
                    results=[],
                    warnings=[
                        "More than one registered character has this name. Select a character and collection to search a specific identity."
                    ],
                    channels=[],
                    partial=True,
                )
            character_ids = [values[0]["id"] for values in matches.values()] or None
        requested = characters or self.requested_characters(query, collection_id)
        from searchy.retrieval.understanding import clothing_query as outfit_query
        from searchy.retrieval.understanding import understand

        plan = understand(query, requested)
        graph_query = " ".join(sorted(plan.content_tokens))
        identity_filter = {"character_ids": character_ids} if character_ids else {}
        warnings = []
        if not any(
            c["indexed_scenes"]
            for c in self.metadata.collections()
            if collection_id is None or c["collection_id"] == collection_id
        ):
            return dict(
                query=query,
                results=[],
                warnings=["No indexed scenes in this collection"],
                channels=[],
                partial=False,
            )
        channels = {}
        errors = []
        operations = []
        if mode == "hybrid" and plan.quoted and not plan.needs_graph:
            matches = []
            _, records, _ = self.metadata.catalog_records()
            for scene, indexed in records:
                if not indexed or (collection_id and scene.collection_id != collection_id):
                    continue
                if character_ids and not set(character_ids) <= set(scene.character_ids):
                    continue
                if not all(
                    any(character_matches(c, name) for c in scene.characters) for name in requested
                ):
                    continue
                if dialogue_matches(
                    " ".join(d.text for d in scene.dialogue), list(plan.quoted), set()
                ):
                    matches.append(Candidate(scene_id=scene.scene_id, score=1, channel="dialogue"))
            channels["dialogue"] = matches[: self.settings.candidate_limit]
        if mode == "graph" or (mode == "hybrid" and plan.needs_graph):
            operations.append(
                (
                    "graph",
                    lambda: self.graph.search(
                        graph_query,
                        requested,
                        collection_id,
                        self.settings.candidate_limit,
                        **identity_filter,
                    ),
                )
            )
        if mode in {"hybrid", "text"}:
            operations.append(
                (
                    "text",
                    lambda: self.vectors.search(
                        query, collection_id, self.settings.candidate_limit, **identity_filter
                    ),
                )
            )
        if mode == "visual" or (mode == "hybrid" and self.settings.visual_enabled):
            operations.append(
                (
                    "visual",
                    lambda: self.vectors.search(
                        query,
                        collection_id,
                        self.settings.candidate_limit,
                        visual=True,
                        **identity_filter,
                    ),
                )
            )
        for name, operation in operations:
            try:
                channels[name] = operation()
            except SearchyError as exc:
                errors.append(str(exc))
                warnings.append(f"{name} retrieval unavailable: {exc}")
        if not channels:
            raise SearchyError("Retrieval is unavailable. " + "; ".join(errors))

        fused = defaultdict(float)
        evidence = defaultdict(set)
        matched_channels = defaultdict(dict)
        for name, candidates in channels.items():
            threshold = (
                self.settings.visual_min_score
                if name == "visual"
                else self.settings.semantic_min_score
                if name == "text"
                else 0
            )
            for rank, candidate in enumerate(candidates, 1):
                if candidate.score < threshold:
                    continue
                fused[candidate.scene_id] += 1 / (60 + rank)
                evidence[candidate.scene_id].update(candidate.evidence)
                matched_channels[candidate.scene_id][name] = candidate.score

        query_tokens = set(plan.content_tokens) | {t for name in requested for t in tokens(name)}
        name_tokens = {t for name in requested for t in tokens(name)}
        content_tokens = query_tokens - name_tokens
        action_terms = normalized_terms(" ".join(content_tokens)) & ACTION_WORDS
        quoted = re.findall(r'["“](.+?)["”]', query)
        dialogue_intent = bool(
            quoted or re.search(r"\b(says?|saying|dialogue|quote)\b", query.lower())
        )
        dialogue_target = content_tokens - {"dialogue", "quote"}
        clothing_query = outfit_query(query)
        if dialogue_intent:
            action_terms = set()
            if not re.search(
                r"\b(wearing|wears|outfits?|clothes|clothing)\b", clothing_query, re.IGNORECASE
            ):
                clothing_query = ""
        results = []
        for scene_id, fusion in fused.items():
            scene = self.metadata.get_scene(scene_id)
            if not scene or not self.metadata.is_indexed(scene_id):
                continue
            if collection_id is not None and scene.collection_id != collection_id:
                continue
            if character_ids and not set(character_ids) <= set(scene.character_ids):
                continue
            if not all(
                any(character_matches(c, name) for c in scene.characters) for name in requested
            ):
                continue
            if not clothing_matches(clothing_query, scene, requested, character_ids):
                continue
            timing = simultaneous_timing(query, scene, requested, character_ids, action_terms)
            if timing == "disjoint":
                continue
            transcript = " ".join(d.text for d in scene.dialogue)
            if dialogue_intent and not dialogue_matches(transcript, quoted, dialogue_target):
                continue
            observed = normalized_terms(scene.search_text())
            missing_content = sorted(
                term for term in content_tokens if NORMALIZED_WORDS.get(term, term) not in observed
            )
            if missing_content and not ({"text", "visual"} & matched_channels[scene_id].keys()):
                continue
            association_unverified = bool(
                requested
                and action_terms
                and action_terms <= observed
                and not all(
                    any(
                        o.kind in {"action", "interaction"}
                        and o.subject
                        and character_matches(o.subject, name)
                        and action_terms <= normalized_terms(o.value)
                        for o in scene.observations
                    )
                    for name in requested
                )
            )
            if character_ids and action_terms and action_terms <= observed:
                association_unverified = not all(
                    any(
                        o.kind in {"action", "interaction"}
                        and identity_key(scene, o.subject, o.subject_id) == identifier
                        and action_terms <= normalized_terms(o.value)
                        for o in scene.observations
                    )
                    for identifier in character_ids
                )
            missing = missing_content + (
                ["character action association"] if association_unverified else []
            )
            if timing == "unverified":
                missing.append("simultaneous timing unverified")
            speaker_unverified = bool(
                dialogue_intent
                and requested
                and not all(
                    speaker_matches(scene, name, quoted, dialogue_target) for name in requested
                )
            )
            if character_ids and dialogue_intent:
                speaker_unverified = not all(
                    speaker_matches(scene, "", quoted, dialogue_target, identifier)
                    for identifier in character_ids
                )
            if speaker_unverified:
                missing.append("character dialogue association")
            overlap = (len(content_tokens) - len(missing_content)) / max(1, len(content_tokens))
            lexical_evidence = [
                o.evidence
                for o in scene.observations
                if normalized_terms(o.value) & normalized_terms(" ".join(content_tokens))
                or any(character_matches(o.value, name) for name in requested)
            ]
            relevant_dialogue = [
                d.model_dump() for d in scene.dialogue if tokens(d.text) & content_tokens
            ]
            supporting = list(dict.fromkeys([*lexical_evidence, *sorted(evidence[scene_id])]))[:8]
            score = (
                fusion * 20
                + overlap * 0.6
                - len(missing_content) / max(1, len(content_tokens)) * 0.3
            )
            if association_unverified or speaker_unverified or timing == "unverified":
                score -= 0.15
            if "graph" in matched_channels[scene_id] and len(matched_channels[scene_id]) > 1:
                score += 0.08
            results.append(
                {
                    "scene_id": scene.scene_id,
                    "video_id": scene.video_id,
                    "episode_id": scene.episode_id,
                    "collection_id": scene.collection_id,
                    "start": scene.start,
                    "end": scene.end,
                    "timestamp_basis": scene.timestamp_basis,
                    "description": scene.description[:700],
                    "matching_characters": scene.characters,
                    "matching_character_ids": scene.character_ids,
                    "evidence_timestamps": sorted(
                        {
                            observation.start
                            for observation in scene.observations
                            if observation.start is not None
                            and observation.provenance.verified
                            and (
                                not character_ids
                                or observation.character_id in character_ids
                                or observation.subject_id in character_ids
                            )
                        }
                    ),
                    "dialogue": relevant_dialogue[:8],
                    "score": round(score, 6),
                    "channel_scores": matched_channels[scene_id],
                    "evidence": supporting,
                    "provenance": [p.model_dump() for p in scene.provenance],
                    "match_status": (
                        "partial_match"
                        if (association_unverified or speaker_unverified or timing == "unverified")
                        and not missing_content
                        else "metadata_match"
                        if not missing and (content_tokens or requested)
                        else "semantic_candidate"
                    ),
                    "missing_terms": missing,
                    "playback": playback(scene),
                }
            )
        results.sort(key=lambda r: (-r["score"], r["scene_id"]))
        if results and any(not p["verified"] for r in results for p in r["provenance"]):
            warnings.append(
                "Results include unverified extracted descriptions; inspect the supporting evidence"
            )
        selected = results[:limit]
        if any(result["missing_terms"] for result in selected):
            warnings.append(
                "Some candidates do not verify every query constraint; inspect missing_terms and evidence"
            )
        if any("character action association" in result["missing_terms"] for result in selected):
            warnings.append(
                "A character-action association is unverified where observations do not identify an explicit subject"
            )
        if any("character dialogue association" in result["missing_terms"] for result in selected):
            warnings.append(
                "A character-dialogue association is unverified because the matching speech has no supported speaker identity"
            )
        if character_ids and not selected:
            named = [character for character in registered if character["id"] in character_ids]
            if named:
                pending = [
                    character["name"]
                    for character in named
                    if character.get("recognition_status") != "ready"
                ]
                if pending:
                    warnings.append(
                        f"{', '.join(pending)} has no indexed appearances yet. "
                        "Appearance recognition has to finish before a name search can return that identity."
                    )
                else:
                    warnings.append(
                        "No indexed scenes are associated with "
                        + ", ".join(character["name"] for character in named)
                        + "."
                    )
        return dict(
            query=query,
            results=selected,
            warnings=warnings,
            channels=list(channels),
            partial=bool(errors) or any(result["missing_terms"] for result in selected),
        )
