from collections import Counter, defaultdict
from pathlib import Path

from searchy.api.schemas import (
    CharacterSummary,
    LibraryResponse,
    LibraryVideo,
    WorkspaceCapabilities,
    WorkspaceMetrics,
    WorkspaceResponse,
    public_job,
)
from searchy.core.config import Settings
from searchy.domain import ObservationKind, Scene, Video, stable_id
from searchy.retrieval.search import scene_view
from searchy.storage.metadata import MetadataStore


class CatalogService:
    def __init__(self, metadata: MetadataStore, settings: Settings):
        self.metadata = metadata
        self.settings = settings

    @staticmethod
    def playable(scene: Scene) -> bool:
        return bool(scene.media and Path(scene.media.path).is_file())

    def _video_status(self, video: Video, counts: dict, jobs: list[dict]) -> str:
        for job in jobs:
            payload = job["payload"]
            if payload.get("collection_id") != video.collection_id:
                continue
            if job["kind"] == "upload":
                if public_job(job).get("video_id") != video.video_id:
                    continue
            elif job["kind"] == "import":
                if video.source_kind != "import":
                    continue
                root = Path(payload.get("root", ""))
                if (
                    root.resolve() != self.settings.import_root.resolve()
                    and root.name != video.original_id.strip()
                ):
                    continue
            else:
                continue
            if job["status"] in {"running", "queued", "failed"}:
                return {"running": "processing", "queued": "queued", "failed": "failed"}[
                    job["status"]
                ]
            break
        if counts["scene_count"] and counts["indexed_scenes"] == counts["scene_count"]:
            return "ready"
        return "partial" if counts["scene_count"] else "empty"

    def _library(
        self, videos: list[Video], scenes: list[tuple[Scene, bool]], jobs: list[dict]
    ) -> list[LibraryVideo]:
        by_video = defaultdict(list)
        for scene, indexed in scenes:
            by_video[scene.video_id].append((scene, indexed))
        result = []
        for video in videos:
            rows = sorted(
                by_video[video.video_id],
                key=lambda row: (row[0].start is None, row[0].start or 0, row[0].scene_id),
            )
            playable = [scene for scene, _ in rows if self.playable(scene)]
            counts = {
                "scene_count": len(rows),
                "indexed_scenes": sum(indexed for _, indexed in rows),
                "playable_scenes": len(playable),
            }
            result.append(
                LibraryVideo(
                    **video.model_dump(exclude={"media_path"}),
                    **counts,
                    thumbnail_scene_id=playable[0].scene_id if playable else None,
                    status=self._video_status(video, counts, jobs),
                    characters=sorted({name for scene, _ in rows for name in scene.characters}),
                )
            )
        return sorted(result, key=lambda item: (item.title.casefold(), item.video_id))

    def library(
        self, limit: int = 100, offset: int = 0, q: str = "", collection_id: str | None = None
    ) -> LibraryResponse:
        videos, scenes, jobs = self.metadata.catalog_records()
        query = q.strip().casefold()
        items = [
            video
            for video in self._library(videos, scenes, jobs)
            if (not collection_id or video.collection_id == collection_id)
            and (not query or query in video.title.casefold())
        ]
        return LibraryResponse(items=items[offset : offset + limit], total=len(items))

    def video(self, video_id: str) -> LibraryVideo | None:
        videos, scenes, jobs = self.metadata.catalog_records()
        return next(
            (video for video in self._library(videos, scenes, jobs) if video.video_id == video_id),
            None,
        )

    def workspace(self) -> WorkspaceResponse:
        videos, scenes, jobs = self.metadata.catalog_records()
        playable = [scene for scene, _ in scenes if self.playable(scene)]
        statuses = Counter(job["status"] for job in jobs)
        collection_rows = {}
        for video in videos:
            row = collection_rows.setdefault(
                video.collection_id,
                {
                    "collection_id": video.collection_id,
                    "video_count": 0,
                    "scene_count": 0,
                    "indexed_scenes": 0,
                },
            )
            row["video_count"] += 1
        for scene, indexed in scenes:
            row = collection_rows[scene.collection_id]
            row["scene_count"] += 1
            row["indexed_scenes"] += indexed
        key = (
            self.settings.gemini_api_key
            if self.settings.llm_provider == "GOOGLE_GENAI"
            else self.settings.groq_api_key
        )
        return WorkspaceResponse(
            metrics=WorkspaceMetrics(
                total_videos=len(videos),
                uploaded_videos=sum(video.source_kind == "upload" for video in videos),
                indexed_videos=len({scene.video_id for scene, indexed in scenes if indexed}),
                total_scenes=len(scenes),
                indexed_scenes=sum(indexed for _, indexed in scenes),
                playable_scenes=len(playable),
                metadata_only_scenes=len(scenes) - len(playable),
                running_jobs=statuses["running"],
                queued_jobs=statuses["queued"],
                failed_jobs=statuses["failed"],
                completed_jobs=statuses["completed"],
            ),
            collections=sorted(collection_rows.values(), key=lambda row: row["collection_id"]),
            featured_scenes=[
                scene_view(scene)
                for scene in sorted(
                    playable, key=lambda scene: (scene.episode_id or "", scene.start or 0)
                )[:6]
            ],
            capabilities=WorkspaceCapabilities(
                max_upload_mb=self.settings.max_upload_mb,
                visual_enabled=self.settings.visual_enabled,
                vlm_configured=bool(key.get_secret_value()),
                llm_provider=self.settings.llm_provider,
                llm_model=self.settings.llm_model_id,
                embedding_model=self.settings.embedding_model_id,
            ),
        )

    def _references(self) -> dict[str, Path]:
        directory = self.settings.character_reference_dir
        if directory is None or not directory.is_dir():
            return {}
        return {
            path.stem.casefold(): path
            for path in directory.glob("*.png")
            if path.is_file()
            and not path.is_symlink()
            and path.resolve().is_relative_to(directory.resolve())
        }

    @staticmethod
    def _verified(scene: Scene, name: str) -> bool:
        normalized = name.casefold()
        return any(
            observation.provenance.verified
            and (
                (
                    observation.kind == ObservationKind.CHARACTER
                    and observation.value.casefold() == normalized
                )
                or (observation.subject or "").casefold() == normalized
            )
            for observation in scene.observations
        ) or any(
            (line.speaker or "").casefold() == normalized
            and line.provenance
            and line.provenance.verified
            for line in scene.dialogue
        )

    def characters(self) -> list[CharacterSummary]:
        _, scenes, _ = self.metadata.catalog_records()
        names = defaultdict(list)
        for scene, _ in scenes:
            for name in scene.characters:
                names[name].append(scene)
        references = self._references()
        result = []
        for name, appearances in names.items():
            identifier = stable_id(name)
            reference = references.get(name.casefold())
            unidentified = name.casefold().startswith(
                ("unidentified", "unknown", "unclear", "unrecognized")
            )
            result.append(
                CharacterSummary(
                    id=identifier,
                    name=name,
                    reference_url=f"/api/characters/{identifier}/reference" if reference else None,
                    scene_count=len(appearances),
                    video_count=len({scene.video_id for scene in appearances}),
                    verified_scene_count=sum(self._verified(scene, name) for scene in appearances),
                    identity_status="unidentified"
                    if unidentified
                    else "reference"
                    if reference
                    else "unverified",
                )
            )
        return sorted(result, key=lambda item: (-item.scene_count, item.name.casefold()))

    def reference(self, character_id: str) -> Path | None:
        character = next((item for item in self.characters() if item.id == character_id), None)
        return self._references().get(character.name.casefold()) if character else None

    def character_scenes(self, character_id: str, limit: int, offset: int) -> list[Scene] | None:
        _, scenes, _ = self.metadata.catalog_records()
        matches = [
            scene
            for scene, _ in scenes
            if any(stable_id(name) == character_id for name in scene.characters)
        ]
        if not matches:
            return None
        return sorted(
            matches,
            key=lambda scene: (
                scene.episode_id or scene.video_id,
                scene.start is None,
                scene.start or 0,
            ),
        )[offset : offset + limit]
