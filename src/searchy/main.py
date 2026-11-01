import hashlib
import logging
import re
import secrets
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

from searchy.api.answers import SearchSessionResponse, create_answers_router
from searchy.api.catalog import create_catalog_router
from searchy.api.characters import create_character_router
from searchy.api.exploration import create_exploration_router
from searchy.api.schemas import (
    ImportRequest,
    JobResponse,
    SceneDetail,
    SearchRequest,
    SearchResponse,
    public_job,
)
from searchy.core.config import Settings
from searchy.core.errors import InvalidInput, SearchyError
from searchy.ingestion.importer import inspect_chunks
from searchy.processing.video import VideoProcessor
from searchy.retrieval.search import scene_view
from searchy.services.container import Services
from searchy.worker import Worker

logger = logging.getLogger("searchy")


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings()

    @asynccontextmanager
    async def lifespan(application):
        services = Services(config)
        application.state.services = services
        worker_thread = None
        stop_worker = None
        if config.worker_enabled:
            stop_worker = threading.Event()
            worker = Worker(services)

            def run_worker():
                try:
                    worker.run_forever(stop_worker)
                finally:
                    services.close()

            worker_thread = threading.Thread(
                target=run_worker,
                name="searchy-job-worker",
                daemon=True,
            )
            application.state.worker_thread = worker_thread
            worker_thread.start()
        try:
            yield
        finally:
            if worker_thread is None:
                services.close()
            else:
                stop_worker.set()
                worker_thread.join(config.worker_shutdown_timeout_seconds)
                if worker_thread.is_alive():
                    logger.info("Worker will stop after its active job finishes")

    application = FastAPI(title="Searchy", version="0.1.0", lifespan=lifespan)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-API-Key", "Range"],
        expose_headers=[
            "Content-Range",
            "Accept-Ranges",
            "Content-Length",
            "X-Scene-Start-Offset",
            "X-Scene-Duration",
        ],
    )

    def services():
        return application.state.services

    def authorize(x_api_key: str | None = Header(default=None)):
        configured = config.api_key.get_secret_value()
        if configured and not secrets.compare_digest(x_api_key or "", configured):
            raise HTTPException(401, "A valid X-API-Key is required")

    api = [Depends(authorize)]

    @application.exception_handler(SearchyError)
    async def handle_searchy_error(request, exc):
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

    @application.exception_handler(RequestValidationError)
    async def handle_validation(request, exc):
        return JSONResponse(
            status_code=422,
            content={
                "detail": [
                    {"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]}
                    for e in exc.errors()
                ]
            },
        )

    @application.exception_handler(Exception)
    async def handle_error(request, exc):
        logger.error("Request failed (%s)", type(exc).__name__)
        return JSONResponse(status_code=500, content={"detail": "An internal operation failed"})

    @application.get("/health")
    def health():
        return {"status": "ok"}

    @application.get("/ready")
    def ready(svc=Depends(services)):
        checks = {}
        for name, check in [("neo4j", svc.graph.ready), ("qdrant", svc.vectors.ready)]:
            try:
                check()
                checks[name] = {"ready": True}
            except SearchyError as exc:
                checks[name] = {"ready": False, "detail": str(exc)}
        ok = all(c["ready"] for c in checks.values())
        return JSONResponse(
            status_code=200 if ok else 503,
            content={
                "ready": ok,
                "services": checks,
                "features": {
                    "visual_enabled": config.visual_enabled,
                    "vlm_configured": bool(
                        (
                            config.gemini_api_key
                            if config.llm_provider == "GOOGLE_GENAI"
                            else config.groq_api_key
                        ).get_secret_value()
                    ),
                    "embedding_model": config.embedding_model_id,
                },
            },
        )

    @application.get("/api/imports/inspect", dependencies=api)
    def inventory():
        return inspect_chunks(config.import_root.resolve())

    @application.post("/api/imports", status_code=202, response_model=JobResponse, dependencies=api)
    def start_import(body: ImportRequest, svc=Depends(services)):
        root = config.import_root.resolve()
        target = (root / body.subpath).resolve()
        if not target.is_relative_to(root) or not target.is_dir():
            raise InvalidInput("Import subpath must be an existing directory within IMPORT_ROOT")
        job = svc.metadata.create_job(
            "import",
            {
                "root": str(target),
                "collection_id": body.collection_id,
                "limit": body.limit,
                "force": body.force,
            },
        )
        return public_job(job)

    @application.post(
        "/api/videos/upload", status_code=202, response_model=JobResponse, dependencies=api
    )
    async def upload(
        file: UploadFile = File(...), collection_id: str = Form("uploads"), svc=Depends(services)
    ):
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", collection_id):
            raise InvalidInput(
                "Collection ID must contain 1-80 letters, digits, underscores or hyphens"
            )
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in {".mp4", ".mkv", ".mov", ".webm"} or not (
            file.content_type or ""
        ).startswith("video/"):
            raise InvalidInput("Upload an MP4, MKV, MOV or WebM video with a video content type")
        directory = config.data_dir / "uploads"
        directory.mkdir(parents=True, exist_ok=True)
        temporary = directory / f"{uuid4()}{suffix}"
        digest = hashlib.sha256()
        size = 0
        try:
            with temporary.open("wb") as output:
                while block := await file.read(1024 * 1024):
                    size += len(block)
                    if size > config.max_upload_mb * 1024 * 1024:
                        raise SearchyError("Video exceeds MAX_UPLOAD_MB", 413)
                    digest.update(block)
                    output.write(block)
            if size == 0:
                raise InvalidInput("Video is empty")
            metadata = await run_in_threadpool(VideoProcessor(config).probe, temporary)
            destination = directory / f"{digest.hexdigest()}{suffix}"
            temporary.replace(destination)
            job = svc.metadata.create_job(
                "upload",
                {
                    "path": str(destination.resolve()),
                    "digest": digest.hexdigest(),
                    "title": Path(file.filename or "video").name,
                    "collection_id": collection_id,
                    "duration": metadata.duration,
                },
            )
            return public_job(job)
        finally:
            await file.close()
            temporary.unlink(missing_ok=True)

    @application.get("/api/jobs", response_model=list[JobResponse], dependencies=api)
    def jobs(limit: int = Query(default=50, ge=1, le=200), svc=Depends(services)):
        return [public_job(j) for j in svc.metadata.list_jobs(limit)]

    @application.get("/api/jobs/{job_id}", response_model=JobResponse, dependencies=api)
    def job_status(job_id: str, svc=Depends(services)):
        job = svc.metadata.get_job(job_id)
        if not job:
            raise HTTPException(404, "Job not found")
        return public_job(job)

    @application.post(
        "/api/jobs/{job_id}/retry", status_code=202, response_model=JobResponse, dependencies=api
    )
    def retry_job(job_id: str, svc=Depends(services)):
        job = svc.metadata.get_job(job_id)
        if not job:
            raise HTTPException(404, "Job not found")
        if job["status"] != "failed":
            raise HTTPException(409, "Only failed jobs can be retried")
        return public_job(svc.metadata.create_job(job["kind"], job["payload"]))

    @application.get("/api/collections", dependencies=api)
    def collections(svc=Depends(services)):
        return svc.metadata.collections()

    @application.get("/api/videos", dependencies=api)
    def videos(
        limit: int = Query(default=100, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
        svc=Depends(services),
    ):
        return [
            {
                **row["video"].model_dump(exclude={"media_path"}),
                "scene_count": row["scene_count"],
                "indexed_scenes": row["indexed_scenes"],
            }
            for row in svc.metadata.list_videos(limit, offset)
        ]

    @application.get(
        "/api/videos/{video_id}/scenes", response_model=list[SceneDetail], dependencies=api
    )
    def video_scenes(
        video_id: str,
        limit: int = Query(default=100, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
        svc=Depends(services),
    ):
        if not svc.metadata.get_video(video_id):
            raise HTTPException(404, "Video not found")
        return [scene_view(s) for s in svc.metadata.list_scenes(video_id, limit, offset)]

    @application.post("/api/search", response_model=SearchResponse, dependencies=api)
    def search(body: SearchRequest, svc=Depends(services)):
        if body.mode == "visual" and not config.visual_enabled:
            raise InvalidInput(
                "Enable VISUAL_ENABLED and index scenes with frames to use visual search"
            )
        from searchy.retrieval.understanding import understand

        request = body.model_dump(exclude_none=True)
        result = svc.search.search(**request)
        plan = understand(
            body.query, svc.search.requested_characters(body.query, body.collection_id)
        )
        result["query_plan"] = {"primary_type": plan.primary_type, "types": list(plan.types)}
        svc.sessions.create(request, result)
        return result

    @application.get(
        "/api/search/sessions/{search_id}", response_model=SearchSessionResponse, dependencies=api
    )
    def search_session(search_id: str, svc=Depends(services)):
        saved = svc.sessions.get(search_id)
        return {key: saved.get(key) for key in SearchSessionResponse.model_fields}

    def find_scene(scene_id, svc):
        scene = svc.metadata.get_scene(scene_id)
        if not scene:
            raise HTTPException(404, "Scene not found")
        return scene

    @application.get("/api/scenes/{scene_id}", response_model=SceneDetail, dependencies=api)
    def scene_details(scene_id: str, svc=Depends(services)):
        return scene_view(find_scene(scene_id, svc))

    @application.get("/api/scenes/{scene_id}/media", dependencies=api)
    def media(scene_id: str, svc=Depends(services)):
        scene = find_scene(scene_id, svc)
        if not scene.media or not Path(scene.media.path).is_file():
            raise HTTPException(404, "Source media is unavailable; metadata remains searchable")
        return FileResponse(
            scene.media.path,
            headers={
                "X-Scene-Start-Offset": str(scene.media.start_offset),
                "X-Scene-Duration": str(
                    (scene.end - scene.start) if scene.start is not None else "unknown"
                ),
            },
        )

    application.include_router(create_catalog_router(config, services, authorize))
    application.include_router(create_answers_router(config, services, authorize))
    application.include_router(create_exploration_router(config, services, authorize))
    application.include_router(create_character_router(config, services, authorize))
    return application


app = create_app()
