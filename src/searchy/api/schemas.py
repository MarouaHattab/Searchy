from typing import Literal

from pydantic import Field, field_validator

from searchy.domain import Dialogue, Observation, Provenance, Record, stable_id


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
    character_ids: list[str] | None = Field(default=None, max_length=10)

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
    visual_description: str | None = None
    scene_summary: str = ""
    dialogue: list[Dialogue]
    observations: list[Observation]
    provenance: list[Provenance]
    characters: list[str]
    character_ids: list[str] = Field(default_factory=list)
    related_characters: list[str] = Field(default_factory=list)
    related_character_ids: list[str] = Field(default_factory=list)
    visual_characters: list[str] = Field(default_factory=list)
    visual_character_ids: list[str] = Field(default_factory=list)
    speakers: list[str] = Field(default_factory=list)
    speaker_ids: list[str] = Field(default_factory=list)
    mentioned_characters: list[str] = Field(default_factory=list)
    mentioned_character_ids: list[str] = Field(default_factory=list)
    subject_characters: list[str] = Field(default_factory=list)
    subject_character_ids: list[str] = Field(default_factory=list)
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
    visual_description: str = ""
    scene_summary: str = ""
    visual_characters: list[str] = Field(default_factory=list)
    visual_character_ids: list[str] = Field(default_factory=list)
    speakers: list[str] = Field(default_factory=list)
    speaker_ids: list[str] = Field(default_factory=list)
    mentioned_characters: list[str] = Field(default_factory=list)
    mentioned_character_ids: list[str] = Field(default_factory=list)
    subject_characters: list[str] = Field(default_factory=list)
    subject_character_ids: list[str] = Field(default_factory=list)
    related_characters: list[str] = Field(default_factory=list)
    related_character_ids: list[str] = Field(default_factory=list)
    matching_characters: list[str]
    matching_character_ids: list[str] = Field(default_factory=list)
    evidence_timestamps: list[float] = Field(default_factory=list)
    dialogue: list[Dialogue]
    score: float
    channel_scores: dict[str, float]
    evidence: list[str]
    provenance: list[Provenance]
    match_status: str
    playback: Playback
    missing_terms: list[str] = Field(default_factory=list)


class AggregateResult(Record):
    shape: str
    term: str | None = None
    total: int = 0
    rows: list[dict] = Field(default_factory=list)


class SearchResponse(Record):
    search_id: str | None = None
    query_plan: dict = Field(default_factory=dict)
    query: str
    results: list[SceneMatch]
    warnings: list[str]
    channels: list[str]
    partial: bool
    shape: str = "lookup"
    aggregate: AggregateResult | None = None


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
    title: str | None = None
    collection_id: str | None = None
    video_id: str | None = None


def public_job(job: dict) -> dict:
    result = {k: v for k, v in job.items() if k in JobResponse.model_fields}
    payload = job.get("payload", {})
    collection = payload.get("collection_id")
    result["collection_id"] = collection
    result["title"] = payload.get("title") or (
        f"Import {collection}" if job.get("kind") == "import" and collection else None
    )
    # An upload is imported through the chunk pipeline, so its video id is the
    # importer's episode-derived id, not a digest-derived one. Report whatever
    # the completed job actually created rather than reconstructing it.
    created = (job.get("result") or {}) if isinstance(job.get("result"), dict) else {}
    identifiers = created.get("video_ids") or []
    if identifiers:
        result["video_id"] = identifiers[0]
    elif job.get("kind") == "upload" and collection and payload.get("digest"):
        result["video_id"] = stable_id(f"upload:{collection}:{payload['digest']}")
    return result


class LibraryVideo(Record):
    video_id: str
    collection_id: str
    title: str
    original_id: str
    source_kind: Literal["import", "upload"]
    duration: float | None
    scene_count: int
    indexed_scenes: int
    playable_scenes: int
    thumbnail_scene_id: str | None
    status: Literal["ready", "partial", "processing", "queued", "failed", "empty"]
    characters: list[str]


class LibraryResponse(Record):
    items: list[LibraryVideo]
    total: int


class CharacterSummary(Record):
    id: str
    name: str
    reference_url: str | None
    scene_count: int
    video_count: int
    verified_scene_count: int
    identity_status: Literal["reference", "unverified", "unidentified"]
    origin: Literal["custom", "extracted"] = "extracted"
    collection_id: str | None = None
    video_id: str | None = None
    description: str = ""
    revision: int | None = None
    status: str | None = None
    recognition_status: str | None = None
    reference_count: int = 0
    review_count: int = 0
    accepted_count: int = 0


class WorkspaceMetrics(Record):
    total_videos: int
    uploaded_videos: int
    indexed_videos: int
    total_scenes: int
    indexed_scenes: int
    playable_scenes: int
    metadata_only_scenes: int
    running_jobs: int
    queued_jobs: int
    failed_jobs: int
    completed_jobs: int


class WorkspaceCapabilities(Record):
    max_upload_mb: int
    visual_enabled: bool
    vlm_configured: bool
    llm_provider: str
    llm_model: str
    embedding_model: str


class WorkspaceResponse(Record):
    metrics: WorkspaceMetrics
    collections: list[dict]
    featured_scenes: list[SceneDetail]
    capabilities: WorkspaceCapabilities
