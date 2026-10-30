import json
import queue
import threading
from collections.abc import Iterator
from typing import Literal

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import Field, field_validator

from searchy.core.config import Settings
from searchy.domain import Record
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
    episode_id: str | None = None
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


class AnswerRelationship(Record):
    scene_id: str
    characters: list[str] = Field(default_factory=list)
    entities: dict[str, list[str]] = Field(default_factory=dict)


class AnswerConstraint(Record):
    label: str
    supported: bool
    detail: str


class AnswerResponse(Record):
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


def _events(result: dict) -> Iterator[bytes]:
    """Emit the answer as SSE frames: token chunks, then the full payload."""
    answer = result.get("answer", "")
    words = answer.split(" ") if answer else []
    for index, word in enumerate(words):
        chunk = word + (" " if index < len(words) - 1 else "")
        yield _frame("delta", {"text": chunk})
    yield _frame("answer", result)


def _frame(event: str, payload: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n".encode()


def create_answers_router(settings: Settings, services, authorize) -> APIRouter:
    router = APIRouter(prefix="/api", dependencies=[Depends(authorize)])

    def service(svc) -> AnswerService:
        return AnswerService(settings, svc.metadata, svc.search, graph=svc.graph)

    @router.post("/search/answer", response_model=AnswerResponse)
    def answer(body: AnswerRequest, svc=Depends(services)):
        return service(svc).answer(**body.model_dump())

    @router.post("/search/answer/stream")
    def answer_stream(body: AnswerRequest, svc=Depends(services)):
        """Same result as /search/answer, streamed as Server-Sent Events.

        Generation happens on a worker thread so the response starts immediately and
        the client can render scene results while the answer is still being produced.
        """
        pending: queue.Queue = queue.Queue()

        def run():
            try:
                pending.put(("result", service(svc).answer(**body.model_dump())))
            except Exception as exc:  # surfaced to the client as a typed error frame
                pending.put(("error", {"detail": str(exc)}))

        def stream() -> Iterator[bytes]:
            worker = threading.Thread(target=run, daemon=True)
            worker.start()
            yield _frame("status", {"state": "thinking"})
            while True:
                try:
                    kind, payload = pending.get(timeout=15)
                except queue.Empty:
                    yield _frame("status", {"state": "thinking"})
                    continue
                if kind == "error":
                    yield _frame("error", payload)
                    return
                yield from _events(payload)
                yield _frame("done", {"status": payload.get("status")})
                return

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return router
