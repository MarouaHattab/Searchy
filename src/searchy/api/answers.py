import json
from typing import Literal

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import ConfigDict, Field, field_validator

from searchy.core import Settings
from searchy.domain import Record
from .exploration import GraphResponse, GraphSupport
from .schemas import SearchRequest, SearchResponse


class AnswerRequest(Record):
    search_id: str | None = Field(default=None, max_length=80)
    query: str = Field(min_length=1, max_length=2000)
    scene_ids: list[str] = Field(max_length=12)
    collection_id: str | None = Field(default=None, max_length=80)
    character_ids: list[str] | None = Field(default=None, max_length=20)

    @field_validator("query")
    @classmethod
    def query_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Query cannot be blank")
        return value.strip()

    @field_validator("scene_ids")
    @classmethod
    def scene_ids_unique(cls, values: list[str]) -> list[str]:
        if any(not value or len(value) > 160 or value != value.strip() for value in values):
            raise ValueError(
                "Scene identifiers must contain 1-160 characters without surrounding whitespace"
            )
        if len(values) != len(set(values)):
            raise ValueError("Scene identifiers must be unique")
        return values


class AnswerCitation(Record):
    scene_id: str
    label: str
    episode_id: str | None = None
    start: float | None
    end: float | None
    timestamp_basis: str
    available: bool
    url: str
    evidence_ids: list[str] = Field(default_factory=list)


class AnswerEvidence(Record):
    model_config = ConfigDict(extra="ignore")
    evidence_id: str
    scene_id: str
    kind: str
    text: str
    verified: bool
    confidence: float | None = None
    start: float | None = None
    end: float | None = None
    episode_id: str | None = None
    visual_characters: list[str] = Field(default_factory=list)
    evidence_source: str | None = None
    source_start: float | None = None
    source_end: float | None = None
    speaker_id: str | None = None
    speaker_name: str | None = None
    speaker_confidence: float | None = None
    mentioned_characters: list[dict] = Field(default_factory=list)
    subject_characters: list[dict] = Field(default_factory=list)


class AnswerRelationshipLink(Record):
    source: str
    relation: str
    target: str
    target_type: str
    evidence: list[str] = Field(default_factory=list)
    start: float | None = None
    end: float | None = None
    verified: bool | None = None
    supports: list[GraphSupport] = Field(default_factory=list)


class AnswerRelationship(Record):
    scene_id: str
    characters: list[str] = Field(default_factory=list)
    entities: dict[str, list[str]] = Field(default_factory=dict)
    links: list[AnswerRelationshipLink] = Field(default_factory=list)


class AnswerConstraint(Record):
    label: str
    supported: bool
    detail: str


class AnswerResponse(Record):
    search_id: str | None = None
    graph: GraphResponse = Field(
        default_factory=lambda: GraphResponse(
            nodes=[], edges=[], scene_ids=[], warnings=[], truncated=False
        )
    )
    retrieval: dict = Field(default_factory=dict)
    status: Literal["generated", "unavailable", "insufficient_evidence"]
    answer: str = ""
    markdown: str = ""
    claims: list[dict] = Field(default_factory=list)
    citations: list[AnswerCitation] = Field(default_factory=list)
    evidence: list[AnswerEvidence] = Field(default_factory=list)
    relationships: list[AnswerRelationship] = Field(default_factory=list)
    constraints: list[AnswerConstraint] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    provider: str | None = None
    model: str | None = None
    query_type: str | None = None


class SearchSessionResponse(Record):
    request: SearchRequest
    response: SearchResponse
    answer: AnswerResponse | None = None


class SearchContextResponse(Record):
    search_id: str | None
    scene_ids: list[str]
    graph: GraphResponse
    evidence: list[AnswerEvidence]
    warnings: list[str]
    query_type: str
    used_for_answer: bool
    retrieval: dict


def _frame(event: str, payload: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n".encode()


def create_answers_router(settings: Settings, services, authorize) -> APIRouter:
    from searchy.services import AnswerService
    router = APIRouter(prefix="/api", dependencies=[Depends(authorize)])

    def service(svc) -> AnswerService:
        return AnswerService(settings, svc.metadata, svc.search, graph=svc.graph)

    @router.post("/search/answer", response_model=AnswerResponse)
    def answer(body: AnswerRequest, svc=Depends(services)):
        return service(svc).answer(**body.model_dump())

    @router.post("/search/context", response_model=SearchContextResponse)
    def context(body: AnswerRequest, svc=Depends(services)):
        return service(svc).context(**body.model_dump())

    @router.post("/search/answer/stream")
    async def answer_stream(body: AnswerRequest, svc=Depends(services)):
        async def stream():
            try:
                async for event, payload in service(svc).stream(**body.model_dump()):
                    if event == "answer":
                        payload = AnswerResponse.model_validate(payload).model_dump()
                    yield _frame(event, payload)
            except Exception:
                yield _frame(
                    "error",
                    {
                        "detail": "The answer stream was interrupted. Your scene results remain available."
                    },
                )

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return router
