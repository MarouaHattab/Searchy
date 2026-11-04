import re
from enum import StrEnum
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator


def stable_id(value: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"searchy:{value}"))


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Provenance(Record):
    source: str
    method: str
    model: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    verified: bool = False


class DialogueReference(Record):
    name: str = Field(min_length=1)
    character_id: str | None = None
    relation: Literal["mentioned", "subject"]
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidence: str | None = None


class Dialogue(Record):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    text: str = Field(min_length=1)
    speaker: str | None = None
    speaker_id: str | None = None
    speaker_name: str | None = None
    speaker_confidence: float | None = Field(default=None, ge=0, le=1)
    source_start: float | None = Field(default=None, ge=0)
    source_end: float | None = Field(default=None, gt=0)
    references: list[DialogueReference] = Field(default_factory=list)
    provenance: Provenance | None = None

    @model_validator(mode="after")
    def validate_interval(self):
        if self.end <= self.start:
            raise ValueError("Dialogue end must be greater than start")
        if (self.source_start is None) != (self.source_end is None):
            raise ValueError("Dialogue source interval requires both timestamps")
        if self.source_start is not None and self.source_end <= self.source_start:
            raise ValueError("Dialogue source end must be greater than source start")
        return self


class ObservationKind(StrEnum):
    CHARACTER = "character"
    PROFESSION = "profession"
    CLOTHING = "clothing"
    ACTION = "action"
    OBJECT = "object"
    LOCATION = "location"
    INTERACTION = "interaction"


class Observation(Record):
    kind: ObservationKind
    value: str = Field(min_length=1)
    subject: str | None = None
    character_id: str | None = None
    subject_id: str | None = None
    evidence: str = Field(min_length=1)
    start: float | None = Field(default=None, ge=0)
    end: float | None = Field(default=None, ge=0)
    provenance: Provenance


class Media(Record):
    path: str
    start_offset: float = Field(default=0, ge=0)
    duration: float | None = Field(default=None, gt=0)


class Frame(Record):
    path: str
    timestamp: float = Field(ge=0)


class Scene(Record):
    scene_id: str
    video_id: str
    collection_id: str
    episode_id: str | None = None
    source_chunk: str | None = None
    start: float | None = Field(default=None, ge=0)
    end: float | None = Field(default=None, ge=0)
    timestamp_basis: str = "unknown"
    description: str = ""
    visual_description: str | None = None
    scene_summary: str = ""
    dialogue: list[Dialogue] = Field(default_factory=list)
    observations: list[Observation] = Field(default_factory=list)
    provenance: list[Provenance] = Field(default_factory=list)
    media: Media | None = None
    frames: list[Frame] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_interval(self):
        if (self.start is None) != (self.end is None):
            raise ValueError("Scene start and end must both be provided or both be absent")
        if self.start is not None and self.end <= self.start:
            raise ValueError("Scene end must be greater than start")
        for observation in self.observations:
            if (observation.start is None) != (observation.end is None):
                raise ValueError("Observation interval requires both start and end")
            if observation.start is not None:
                if observation.end < observation.start:
                    raise ValueError("Observation end precedes start")
                if self.start is not None and not (
                    self.start <= observation.start <= observation.end <= self.end
                ):
                    raise ValueError("Observation interval must be inside its scene")
        if self.start is not None and self.end is not None:
            for line in self.dialogue:
                if not (max(self.start, line.start) < min(self.end, line.end)):
                    raise ValueError("Dialogue interval must overlap its scene")
        return self

    def owns_dialogue(self, line: Dialogue) -> bool:
        """Determines canonical chunk ownership of a dialogue line.
        A dialogue line is canonically owned by the scene where its speech begins.
        """
        if self.start is None or self.end is None:
            return True
        return self.start <= line.start < self.end

    @property
    def canonical_dialogue(self) -> list[Dialogue]:
        """Returns the non-overlapping canonical dialogue lines owned by this scene."""
        return [line for line in self.dialogue if self.owns_dialogue(line)]

    @property
    def character_ids(self) -> list[str]:
        def identifier(name: str, explicit: str | None):
            normalized = " ".join(name.casefold().split())
            return explicit or stable_id(f"character:{self.collection_id}:{normalized}")

        identifiers = {
            identifier(o.value, o.character_id)
            for o in self.observations
            if o.kind == ObservationKind.CHARACTER
        }
        identifiers.update(
            identifier(o.subject, o.subject_id) for o in self.observations if o.subject
        )
        identifiers.update(identifier(d.speaker, d.speaker_id) for d in self.dialogue if d.speaker)
        return sorted(identifiers)

    @property
    def characters(self) -> list[str]:
        names = {o.value for o in self.observations if o.kind == ObservationKind.CHARACTER}
        names.update(
            o.subject
            for o in self.observations
            if o.subject
            and o.kind
            in {
                ObservationKind.CLOTHING,
                ObservationKind.ACTION,
                ObservationKind.INTERACTION,
            }
        )
        names.update(d.speaker for d in self.dialogue if d.speaker)
        return sorted(names)

    @property
    def related_characters(self) -> list[str]:
        return sorted(
            set(self.characters)
            | {reference.name for line in self.dialogue for reference in line.references}
        )

    @property
    def related_character_ids(self) -> list[str]:
        identifiers = set(self.character_ids)
        identifiers.update(
            reference.character_id
            or stable_id(
                f"character:{self.collection_id}:{' '.join(reference.name.casefold().split())}"
            )
            for line in self.dialogue
            for reference in line.references
        )
        return sorted(identifiers)

    @property
    def visual_characters(self) -> list[str]:
        return sorted(
            {o.value for o in self.observations if o.kind == ObservationKind.CHARACTER}
        )

    @property
    def visual_character_ids(self) -> list[str]:
        return sorted(
            {
                o.character_id or stable_id(
                    f"character:{self.collection_id}:{' '.join(o.value.casefold().split())}"
                )
                for o in self.observations
                if o.kind == ObservationKind.CHARACTER
            }
        )

    @property
    def speakers(self) -> list[str]:
        return sorted({line.speaker for line in self.dialogue if line.speaker})

    @property
    def speaker_ids(self) -> list[str]:
        return sorted(
            {
                line.speaker_id
                or stable_id(
                    f"character:{self.collection_id}:{' '.join(line.speaker.casefold().split())}"
                )
                for line in self.dialogue
                if line.speaker
            }
        )

    @property
    def mentioned_characters(self) -> list[str]:
        return sorted(
            {
                reference.name
                for line in self.dialogue
                for reference in line.references
                if reference.relation == "mentioned"
            }
        )

    @property
    def mentioned_character_ids(self) -> list[str]:
        return sorted(
            {
                reference.character_id
                or stable_id(
                    f"character:{self.collection_id}:{' '.join(reference.name.casefold().split())}"
                )
                for line in self.dialogue
                for reference in line.references
                if reference.relation == "mentioned"
            }
        )

    @property
    def subject_characters(self) -> list[str]:
        return sorted(
            {
                reference.name
                for line in self.dialogue
                for reference in line.references
                if reference.relation == "subject"
            }
        )

    @property
    def subject_character_ids(self) -> list[str]:
        return sorted(
            {
                reference.character_id
                or stable_id(
                    f"character:{self.collection_id}:{' '.join(reference.name.casefold().split())}"
                )
                for line in self.dialogue
                for reference in line.references
                if reference.relation == "subject"
            }
        )

    @property
    def visual_text(self) -> str:
        return visual_description(self.visual_description or self.description)

    def search_text(self) -> str:
        return "\n".join(
            [
                self.visual_text,
                self.scene_summary,
                *[f"{o.subject or ''} {o.kind.value}: {o.value}" for o in self.observations],
                *[d.text for d in self.dialogue],
            ]
        ).strip()


_VISUAL_SECTIONS = {
    "SCENE SETTING",
    "CHARACTERS PRESENT",
    "ACTIONS AND INTERACTIONS",
    "OBJECTS AND PROPS",
    "TEMPORAL NOTES",
}
_ALL_CAPTION_SECTIONS = _VISUAL_SECTIONS | {"DIALOGUE CONTEXT"}


def visual_description(text: str) -> str:
    """Return only visual sections from current or previously imported captions."""
    lines = text.splitlines()
    sections: list[tuple[str, list[str]]] = []
    current: str | None = None
    found_heading = False
    for line in lines:
        heading = re.sub(r"^[#*\s]+|[*\s:]+$", "", line).strip().upper()
        if heading in _ALL_CAPTION_SECTIONS:
            found_heading = True
            current = heading
            sections.append((heading, []))
        elif line.lstrip().startswith("#"):
            current = None
        elif current and line.strip():
            sections[-1][1].append(line.strip())
    if found_heading:
        return "\n".join(
            f"{heading}:\n" + "\n".join(body)
            for heading, body in sections
            if heading in _VISUAL_SECTIONS and body
        ).strip()

    # Legacy unstructured descriptions occasionally embedded this section inline.
    cleaned = re.sub(
        r"(?is)(?:^|\n)\s*(?:#+\s*|\*\*)?DIALOGUE CONTEXT\b.*?(?=(?:\n\s*(?:#+\s*|\*\*)?(?:SCENE SETTING|CHARACTERS PRESENT|ACTIONS AND INTERACTIONS|OBJECTS AND PROPS|TEMPORAL NOTES)\b)|\Z)",
        "\n",
        text,
    )
    return cleaned.strip()


class Video(Record):
    video_id: str
    collection_id: str
    title: str
    original_id: str
    source_kind: Literal["import", "upload"]
    duration: float | None = Field(default=None, gt=0)
    media_path: str | None = None


class Candidate(Record):
    scene_id: str
    score: float
    channel: str
    evidence: list[str] = Field(default_factory=list)


class SummaryEvent(Record):
    event_id: str
    description: str
    characters_involved: list[str] = Field(default_factory=list)
    supporting_scene_ids: list[str] = Field(default_factory=list)
    supporting_timestamps: list[list[float]] = Field(default_factory=list)


class EpisodeSummary(Record):
    episode_id: str
    collection_id: str = "friends"
    title: str
    season_number: int = 1
    episode_number: int
    macro_summary: str
    events: list[SummaryEvent] = Field(default_factory=list)
