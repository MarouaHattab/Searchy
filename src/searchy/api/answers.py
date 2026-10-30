from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import Field, field_validator

from searchy.core.config import Settings
from searchy.domain import Record
from searchy.models.answers import GeneratedClaim
from searchy.services.answers import AnswerService


class AnswerRequest(Record):
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
    start: float | None
    end: float | None
    timestamp_basis: str
    available: bool
    url: str


class AnswerEvidence(Record):
    evidence_id: str
    scene_id: str
    kind: str
    text: str
    verified: bool
    confidence: float | None
    start: float | None
    end: float | None


class AnswerResponse(Record):
    status: Literal["generated", "unavailable", "insufficient_evidence"]
    markdown: str
    claims: list[GeneratedClaim]
    citations: list[AnswerCitation]
    evidence: list[AnswerEvidence]
    warnings: list[str]
    provider: str | None
    model: str | None


def create_answers_router(settings: Settings, services, authorize) -> APIRouter:
    router = APIRouter(prefix="/api", dependencies=[Depends(authorize)])

    @router.post("/search/answer", response_model=AnswerResponse)
    def answer(body: AnswerRequest, svc=Depends(services)):
        return AnswerService(settings, svc.metadata, svc.search).answer(**body.model_dump())

    return router
