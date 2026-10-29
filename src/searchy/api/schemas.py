from typing import Literal

from pydantic import Field, field_validator

from searchy.domain import Dialogue, Observation, Provenance, Record


class ImportRequest(Record):
    collection_id: str = Field(default="friends", pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    subpath: str = ""
    limit: int | None = Field(default=None, ge=1, le=100000)
    force: bool = False


class SearchRequest(Record):
    query: str = Field(min_length=1, max_length=2000)
    limit: int = Field(default=10, ge=1, le=100)
    collection_id: str | None = Field(default=None, max_length=80)
    mode: Literal["hybrid", "text", "graph", "visual"] = "hybrid"
    characters: list[str] | None = Field(default=None, max_length=10)

    @field_validator("query")
    @classmethod
    def query_not_empty(cls, value):
        if not value.strip():
            raise ValueError("Query cannot be blank")
        return value.strip()


class Playback(Record):
    available: bool
    url: str | None
    start_offset: float | None
    reason: str | None


class SceneDetail(Record):
    scene_id: str
    video_id: str
    collection_id: str
    episode_id: str | None
    source_chunk: str | None
    start: float | None
    end: float | None
    timestamp_basis: str
    description: str
    dialogue: list[Dialogue]
    observations: list[Observation]
    provenance: list[Provenance]
    characters: list[str]
    playback: Playback


class SceneMatch(Record):
    scene_id: str
    video_id: str
    collection_id: str
    episode_id: str | None
    start: float | None
    end: float | None
    timestamp_basis: str
    description: str
    matching_characters: list[str]
    dialogue: list[Dialogue]
    score: float
    channel_scores: dict[str, float]
    evidence: list[str]
    provenance: list[Provenance]
    match_status: str
    playback: Playback
    missing_terms: list[str] = Field(default_factory=list)


class SearchResponse(Record):
    query: str
    results: list[SceneMatch]
    warnings: list[str]
    channels: list[str]
    partial: bool


class JobResponse(Record):
    job_id: str
    kind: str
    status: str
    progress: float
    stage: str
    error: str | None
    result: dict | None
    created_at: float
    updated_at: float
    attempts: int


def public_job(job: dict) -> dict:
    return {k: v for k, v in job.items() if k in JobResponse.model_fields}
