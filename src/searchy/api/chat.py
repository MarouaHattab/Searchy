import asyncio
import json
import threading

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import Field, field_validator

from searchy.core.config import Settings
from searchy.domain import Record
from searchy.services.chat import ChatService


class ChatRequest(Record):
    question: str = Field(min_length=1, max_length=2000)
    conversation_id: str | None = Field(default=None, max_length=80)
    collection_id: str | None = Field(default=None, max_length=80)
    character_ids: list[str] | None = Field(default=None, max_length=20)

    @field_validator("question")
    @classmethod
    def question_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Question cannot be blank")
        return value.strip()


class ChatSource(Record):
    number: int
    scene_id: str
    label: str
    start: float | None = None
    end: float | None = None
    timestamp_basis: str = ""
    available: bool = False
    snippet: str = ""


class ChatReply(Record):
    conversation_id: str
    answer: str
    sources: list[ChatSource] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    model: str | None = None


def _frame(event: str, payload: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n".encode()


def create_chat_router(settings: Settings, services, authorize) -> APIRouter:
    router = APIRouter(prefix="/api/chat", dependencies=[Depends(authorize)])

    def service(svc) -> ChatService:
        return ChatService(settings, svc.metadata, svc.search, svc.chat, graph=svc.graph)

    @router.post("", response_model=ChatReply)
    def ask(body: ChatRequest, svc=Depends(services)):
        return service(svc).respond(
            body.question, body.conversation_id, body.collection_id, body.character_ids
        )

    @router.post("/stream")
    async def ask_stream(body: ChatRequest, svc=Depends(services)):
        chat = service(svc)
        conversation = chat.chat.ensure(body.conversation_id, title=body.question[:120])
        chat.chat.append(conversation, "user", body.question)

        async def stream():
            yield _frame("start", {"conversation_id": conversation})
            # The generator is synchronous and does blocking work, so it runs in a
            # worker thread and hands each event over through a queue. Collecting
            # it first would defeat streaming, which is what turned the answer
            # into one final chunk instead of a typing effect.
            queue: asyncio.Queue = asyncio.Queue()
            finish = object()

            def produce():
                try:
                    for event, payload in chat.stream(
                        body.question, conversation, body.collection_id, body.character_ids
                    ):
                        asyncio.run_coroutine_threadsafe(
                            queue.put((event, payload)), loop
                        ).result()
                except Exception as exc:  # noqa: BLE001 - surfaced to the client
                    asyncio.run_coroutine_threadsafe(
                        queue.put(("error", {"detail": str(exc)[:200]})), loop
                    ).result()
                finally:
                    asyncio.run_coroutine_threadsafe(queue.put(finish), loop).result()

            loop = asyncio.get_running_loop()
            worker = threading.Thread(target=produce, daemon=True)
            worker.start()
            final = None
            try:
                while True:
                    item = await queue.get()
                    if item is finish:
                        break
                    event, payload = item
                    if event == "answer":
                        final = payload
                        continue
                    yield _frame(event, payload)
            finally:
                worker.join(timeout=1)
            if final:
                chat.chat.append(
                    conversation,
                    "assistant",
                    final["answer"],
                    {"sources": final["sources"], "model": final["model"]},
                )
                yield _frame("answer", {**final, "conversation_id": conversation})

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @router.get("/conversations")
    def conversations(svc=Depends(services)):
        return svc.chat.list_conversations()

    @router.get("/conversations/{conversation_id}")
    def conversation(conversation_id: str, svc=Depends(services)):
        return {
            "conversation_id": conversation_id,
            "messages": svc.chat.messages(conversation_id),
        }

    @router.delete("/conversations/{conversation_id}")
    def delete_conversation(conversation_id: str, svc=Depends(services)):
        svc.chat.delete(conversation_id)
        return {"deleted": True}

    return router


async def _run(conversation_id: str | None, question: str, svc) -> str:
    return svc.chat.ensure(conversation_id, title=question[:120])
