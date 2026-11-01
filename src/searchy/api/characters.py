from typing import Literal

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import Field
from starlette.concurrency import run_in_threadpool

from searchy.api.schemas import JobResponse
from searchy.core.errors import InvalidInput
from searchy.domain import Record
from searchy.services.characters import CharacterService


class CharacterCreate(Record):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=2000)
    collection_id: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    video_id: str | None = Field(default=None, max_length=100)


class CharacterEdit(Record):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2000)
    collection_id: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    video_id: str | None = Field(default=None, max_length=100)


class CharacterReference(Record):
    id: str
    width: int
    height: int
    validation: Literal["image_validated", "face_ready", "rejected", "failed"]
    error: str | None
    url: str


class CharacterDetails(Record):
    id: str
    name: str
    description: str
    collection_id: str
    video_id: str | None
    revision: int
    status: Literal["unprocessed", "queued", "processing", "ready", "failed"]
    recognition_status: Literal["unprocessed", "queued", "processing", "ready", "failed"]
    created_at: float
    updated_at: float
    references: list[CharacterReference]
    reference_url: str | None
    identity_status: Literal["reference", "unverified", "unidentified"]
    scene_count: int
    video_count: int
    verified_scene_count: int
    review_count: int = 0
    accepted_count: int = 0
    origin: Literal["custom"]


class ReferenceChange(Record):
    character: CharacterDetails
    job: JobResponse | None


class CharacterDeleted(Record):
    id: str
    deleted: bool


class MatchReview(Record):
    status: Literal["accepted", "rejected"]


class CharacterMatch(Record):
    id: str
    character_id: str
    revision: int
    scene_id: str
    timestamp: float
    method: str
    model_id: str
    confidence: float
    evidence: str
    qualified: bool
    verified: bool = False
    status: Literal["pending", "accepted", "rejected"]
    index_status: str
    created_at: float
    updated_at: float
    frame_url: str | None = None


def create_character_router(settings, services, authorize) -> APIRouter:
    router = APIRouter(prefix="/api/characters", dependencies=[Depends(authorize)])

    def characters(svc=Depends(services)):
        service = getattr(svc, "characters", None)
        return service if service is not None else CharacterService(settings, svc.metadata)

    def recognition(svc=Depends(services)):
        return svc.recognition

    @router.post("", status_code=201, response_model=CharacterDetails)
    def create(body: CharacterCreate, service=Depends(characters)):
        return service.create(**body.model_dump())

    @router.get("/{character_id}", response_model=CharacterDetails)
    def detail(character_id: str, service=Depends(characters)):
        return service.get(character_id)

    @router.patch("/{character_id}", response_model=CharacterDetails)
    def update(
        character_id: str, body: CharacterEdit, service=Depends(characters), svc=Depends(services)
    ):
        previous = service.get(character_id)
        changes = body.model_dump(exclude_unset=True)
        scope_changed = (
            changes.get("collection_id") is not None
            and changes["collection_id"] != previous["collection_id"]
        ) or (changes.get("video_id", previous["video_id"]) != previous["video_id"])
        character = service.update(character_id, **changes)
        if scope_changed:
            svc.recognition.remove_identity(character_id)
            if character["status"] == "ready" and character["references"]:
                svc.recognition.start(character_id)
            character = service.get(character_id)
        if character["name"] != previous["name"]:
            svc.metadata.create_job(
                "character_identity_sync",
                {
                    "character_id": character_id,
                    "revision": character["revision"],
                    "collection_id": character["collection_id"],
                    "title": f"Update {character['name']} identity",
                },
            )
        return character

    @router.delete("/{character_id}", response_model=CharacterDeleted)
    def delete(character_id: str, service=Depends(characters), matches=Depends(recognition)):
        matches.remove_identity(character_id, deleting=True)
        return service.delete(character_id)

    @router.post("/{character_id}/references", status_code=202, response_model=ReferenceChange)
    async def add_references(
        character_id: str,
        files: list[UploadFile] = File(...),
        service=Depends(characters),
        matches=Depends(recognition),
    ):
        try:
            if not 1 <= len(files) <= 5:
                raise InvalidInput("Upload between one and five reference images")
            contents = []
            for file in files:
                content = await file.read(10 * 1024 * 1024 + 1)
                if len(content) > 10 * 1024 * 1024:
                    raise InvalidInput("Reference images must not exceed 10 MB")
                contents.append(content)
            previous = service.get(character_id)
            result = await run_in_threadpool(service.add_references, character_id, contents)
            if result["character"]["revision"] != previous["revision"]:
                await run_in_threadpool(matches.remove_identity, character_id)
                result["character"] = service.get(character_id)
            return result
        finally:
            for file in files:
                await file.close()

    @router.get("/{character_id}/references/{reference_id}")
    def reference(character_id: str, reference_id: str, service=Depends(characters)):
        return FileResponse(
            service.reference_path(character_id, reference_id),
            media_type="image/jpeg",
            headers={"Cache-Control": "private, max-age=3600"},
        )

    @router.delete("/{character_id}/references/{reference_id}", response_model=ReferenceChange)
    def remove_reference(
        character_id: str,
        reference_id: str,
        service=Depends(characters),
        matches=Depends(recognition),
    ):
        result = service.remove_reference(character_id, reference_id)
        matches.remove_identity(character_id)
        result["character"] = service.get(character_id)
        return result

    @router.post(
        "/{character_id}/references/{reference_id}/replace",
        status_code=202,
        response_model=ReferenceChange,
    )
    async def replace_reference(
        character_id: str,
        reference_id: str,
        file: UploadFile = File(...),
        service=Depends(characters),
        matches=Depends(recognition),
    ):
        try:
            content = await file.read(10 * 1024 * 1024 + 1)
            result = await run_in_threadpool(
                service.replace_reference, character_id, reference_id, content
            )
            await run_in_threadpool(matches.remove_identity, character_id)
            result["character"] = service.get(character_id)
            return result
        finally:
            await file.close()

    @router.post("/{character_id}/recognize", status_code=202, response_model=JobResponse)
    def recognize(character_id: str, matches=Depends(recognition)):
        return matches.start(character_id)

    @router.get("/{character_id}/matches", response_model=list[CharacterMatch])
    def list_matches(
        character_id: str,
        limit: int = Query(default=100, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
        matches=Depends(recognition),
    ):
        return matches.matches(character_id, limit, offset)

    @router.patch("/{character_id}/matches/{match_id}", response_model=CharacterMatch)
    def review_match(
        character_id: str, match_id: str, body: MatchReview, matches=Depends(recognition)
    ):
        return matches.review(character_id, match_id, body.status)

    @router.get("/{character_id}/matches/{match_id}/frame")
    def match_frame(character_id: str, match_id: str, matches=Depends(recognition)):
        return FileResponse(
            matches.frame_path(character_id, match_id),
            media_type="image/jpeg",
            headers={"Cache-Control": "private, max-age=3600"},
        )

    return router
