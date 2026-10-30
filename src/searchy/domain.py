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


class Dialogue(Record):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    text: str = Field(min_length=1)
    speaker: str | None = None
    speaker_id: str | None = None
    provenance: Provenance | None = None

    @model_validator(mode="after")
    def validate_interval(self):
        if self.end <= self.start:
            raise ValueError("Dialogue end must be greater than start")
        return self


class ObservationKind(StrEnum):
    CHARACTER = "character"
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
        return self

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

    def search_text(self) -> str:
        return "\n".join(
            [
                self.description,
                *[f"{o.subject or ''} {o.kind.value}: {o.value}" for o in self.observations],
                *[d.text for d in self.dialogue],
            ]
        ).strip()


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
