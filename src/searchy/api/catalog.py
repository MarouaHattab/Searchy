from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response

from searchy.api.schemas import (
    CharacterSummary,
    LibraryResponse,
    LibraryVideo,
    SceneDetail,
    WorkspaceResponse,
)
from searchy.core.config import Settings
from searchy.retrieval.search import scene_view
from searchy.services.catalog import CatalogService
from searchy.services.media import MediaService


def create_catalog_router(settings: Settings, services, authorize) -> APIRouter:
    router = APIRouter(prefix="/api", dependencies=[Depends(authorize)])
    media = MediaService(settings)

    def catalog(svc=Depends(services)):
        return CatalogService(svc.metadata, settings)

    def scene(scene_id: str, svc=Depends(services)):
        result = svc.metadata.get_scene(scene_id)
        if result is None:
            raise HTTPException(404, "Scene not found")
        return result

    @router.get("/workspace", response_model=WorkspaceResponse)
    def workspace(catalog=Depends(catalog)):
        return catalog.workspace()

    @router.get("/library", response_model=LibraryResponse)
    def library(
        limit: int = Query(default=100, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
        q: str = Query(default="", max_length=200),
        collection_id: str | None = Query(default=None, max_length=80),
        catalog=Depends(catalog),
    ):
        return catalog.library(limit, offset, q, collection_id)

    @router.get("/videos/{video_id}", response_model=LibraryVideo)
    def video(video_id: str, catalog=Depends(catalog)):
        result = catalog.video(video_id)
        if result is None:
            raise HTTPException(404, "Video not found")
        return result

    @router.get("/characters", response_model=list[CharacterSummary])
    def characters(catalog=Depends(catalog)):
        return catalog.characters()

    @router.get("/characters/{character_id}/reference")
    def reference(character_id: str, catalog=Depends(catalog)):
        path = catalog.reference(character_id)
        if path is None:
            raise HTTPException(404, "No character reference image is available")
        return FileResponse(path)

    @router.get("/characters/{character_id}/scenes", response_model=list[SceneDetail])
    def character_scenes(
        character_id: str,
        limit: int = Query(default=100, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
        catalog=Depends(catalog),
    ):
        result = catalog.character_scenes(character_id, limit, offset)
        if result is None:
            raise HTTPException(404, "Character not found")
        return [scene_view(item) for item in result]

    @router.get("/scenes/{scene_id}/thumbnail")
    def thumbnail(scene=Depends(scene)):
        return FileResponse(
            media.thumbnail(scene), headers={"Cache-Control": "private, max-age=3600"}
        )

    @router.get("/scenes/{scene_id}/subtitles.vtt")
    def subtitles(scene=Depends(scene)):
        return Response(media.subtitles(scene), media_type="text/vtt")

    return router
