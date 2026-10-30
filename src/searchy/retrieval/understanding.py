import re
from dataclasses import dataclass

from searchy.retrieval.search import (
    ACTION_WORDS,
    CLOTHING_MODIFIERS,
    GARMENTS,
    STOP_WORDS,
    normalized_terms,
    tokens,
)

QUERY_TYPES = {
    "appearance",
    "clothing",
    "object",
    "location",
    "action",
    "dialogue",
    "relationship",
    "event",
    "temporal",
    "visual",
}

_QUOTED = re.compile(r'["“](.+?)["”]')

_DIALOGUE_CUES = re.compile(
    r"\b(says?|said|saying|words?|dialogue|quote[ds]?|line|tells?|told|asks?|asked|mentions?)\b",
    re.I,
)
_CLOTHING_CUES = re.compile(r"\b(wearing|wears?|wore|outfits?|clothes|clothing|dress(?:ed)?)\b", re.I)
_APPEARANCE_CUES = re.compile(
    r"\b(look(?:s|ing)?|appear(?:s|ance)?|hair|beard|glasses|hat|makeup|face)\b", re.I
)
_LOCATION_CUES = re.compile(
    r"\b(in|inside|at|outside|apartment|coffee|shop|central perk|restaurant|office|"
    r"bedroom|kitchen|balcony|where)\b",
    re.I,
)
_OBJECT_CUES = re.compile(
    r"\b(holding|holds?|carrying|carries|object|prop|phone|book|cup|guitar|bag|key|keys)\b",
    re.I,
)
_RELATIONSHIP_CUES = re.compile(
    r"\b(together|with|relationship|dating|married|friends?|between|both|each other|"
    r"couple|argue|arguing|fight|fighting|kiss(?:ing)?|hug(?:ging)?)\b",
    re.I,
)
_CAUSE_CUES = re.compile(
    r"\b(why|because|reason|explain|what happened|how did|what led|motivat\w*)\b", re.I
)
_TEMPORAL_CUES = re.compile(
    r"\b(before|after|then|first|last|next|earlier|later|sequence|happens? (?:before|after)|"
    r"prior|following|previously)\b",
    re.I,
)
_VISUAL_CUES = re.compile(
    r"\b(show|find|picture|image|look like|see|visible|appears? in frame|close-up)\b", re.I
)

# Words that carry no retrieval constraint of their own. Declarative scaffolding only.
SCAFFOLDING_WORDS = {
    "why",
    "what",
    "who",
    "whom",
    "whose",
    "which",
    "how",
    "happen",
    "happens",
    "happened",
    "reason",
    "explain",
    "about",
    "does",
    "did",
    "doing",
    "mean",
    "means",
    "before",
    "after",
    "then",
    "first",
    "last",
    "next",
    "earlier",
    "later",
    "sequence",
    "moment",
    "moments",
    "time",
    "together",
    "between",
    "both",
    "relationship",
    "argue",
    "arguing",
    "argued",
    "argument",
    "fight",
    "fighting",
    "talk",
    "talking",
    "talked",
    "conversation",
    "conversing",
    "chatting",
    "happening",
    "describe",
    "talk about",
}


@dataclass(frozen=True)
class QueryUnderstanding:
    query: str
    types: tuple[str, ...]
    quoted: tuple[str, ...]
    characters: tuple[str, ...]
    clothing: tuple[str, ...]
    action_terms: frozenset[str]
    content_tokens: frozenset[str]
    dialogue_intent: bool
    narrative: bool
    temporal: bool
    missing_constraints: tuple[str, ...]

    @property
    def primary_type(self) -> str:
        return self.types[0] if self.types else "visual"


def garment_phrases(query: str) -> list[str]:
    """Return contiguous modifier+garment phrases such as ``red dress`` or ``black leather jacket``."""
    found: list[str] = []
    current: list[str] = []
    for word in re.findall(r"[a-z0-9]+", query.lower()):
        if word in GARMENTS or word.rstrip("s") in GARMENTS:
            found.append(" ".join([*current, word]))
            current = []
        elif word in CLOTHING_MODIFIERS or word in {"and", "colored", "coloured", "with"}:
            if word not in {"and", "with"}:
                current.append(word)
        else:
            current = []
    return found


def clothing_query(query: str) -> str:
    """The part of the query the outfit matcher should read.

    Behaviour is kept aligned with the search filter: a dialogue question only checks
    clothing when the query explicitly mentions wearing something.
    """
    stripped = _QUOTED.sub("", query)
    if _DIALOGUE_CUES.search(query.casefold()) and not _CLOTHING_CUES.search(stripped):
        return ""
    return stripped


def understand(
    query: str,
    requested_characters: list[str] | tuple[str, ...],
) -> QueryUnderstanding:
    """Extract retrieval constraints and the question's intent.

    This is deterministic and lexical on purpose: it runs on every keystroke-submitted
    query and must be explainable. It is shared by search and answer generation so the
    two cannot drift apart.
    """
    lowered = query.casefold()
    quoted = tuple(match.strip() for match in _QUOTED.findall(query) if match.strip())
    characters = tuple(requested_characters)
    name_tokens = {token for name in characters for token in tokens(name)}
    all_tokens = tokens(query) - STOP_WORDS - SCAFFOLDING_WORDS
    content_tokens = all_tokens - name_tokens

    dialogue_intent = bool(quoted or _DIALOGUE_CUES.search(lowered))
    clothing_query = _QUOTED.sub("", query)
    clothing_cue = bool(_CLOTHING_CUES.search(clothing_query))
    clothing = tuple(garment_phrases(clothing_query))

    action_terms = (
        frozenset()
        if dialogue_intent
        else frozenset(normalized_terms(" ".join(content_tokens)) & ACTION_WORDS)
    )

    narrative = bool(_CAUSE_CUES.search(lowered)) or bool(_RELATIONSHIP_CUES.search(lowered))
    temporal = bool(_TEMPORAL_CUES.search(lowered))

    types: list[str] = []
    if dialogue_intent:
        types.append("dialogue")
    if clothing:
        types.append("clothing")
    if _APPEARANCE_CUES.search(lowered):
        types.append("appearance")
    if action_terms:
        types.append("action")
    if _RELATIONSHIP_CUES.search(lowered):
        types.append("relationship")
    if narrative:
        types.append("event")
    if temporal:
        types.append("temporal")
    if _LOCATION_CUES.search(lowered):
        types.append("location")
    if _OBJECT_CUES.search(lowered):
        types.append("object")
    if not types or _VISUAL_CUES.search(lowered):
        types.append("visual")
    types = list(dict.fromkeys(types))

    hints: list[str] = []
    if dialogue_intent and not quoted:
        hints.append("a quoted line would pin the exact dialogue")
    if clothing_cue and not clothing:
        hints.append("name the garment (for example 'red dress') to check outfits")
    if narrative:
        hints.append(
            "narrative questions are answered only from indexed scenes, not from prior knowledge"
        )
    return QueryUnderstanding(
        query=query,
        types=tuple(types),
        quoted=quoted,
        characters=characters,
        clothing=clothing,
        action_terms=action_terms,
        content_tokens=frozenset(content_tokens),
        dialogue_intent=dialogue_intent,
        narrative=narrative,
        temporal=temporal,
        missing_constraints=tuple(hints),
    )


__all__ = [
    "QUERY_TYPES",
    "SCAFFOLDING_WORDS",
    "QueryUnderstanding",
    "clothing_query",
    "garment_phrases",
    "understand",
]
