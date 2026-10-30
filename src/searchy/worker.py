import argparse
import logging
import threading
import time
from pathlib import Path
from uuid import uuid4

from searchy.core.config import Settings
from searchy.core.errors import SearchyError
from searchy.domain import Provenance, Scene, Video, stable_id
from searchy.ingestion.importer import import_chunks
from searchy.processing.video import VideoProcessor
from searchy.services.container import Services

logger = logging.getLogger("searchy.worker")


class Worker:
    def __init__(self, services):
        self.services = services
        self.settings = services.settings
        self.owner = str(uuid4())

    def prepare_import_frames(self, scenes: list[Scene], progress) -> list[Scene]:
        processor = VideoProcessor(self.settings)
        for index, scene in enumerate(scenes):
            if not scene.media or scene.start is None:
                continue
            progress(0.05 + 0.45 * index / len(scenes), "sampling available imported clips")
            path = Path(scene.media.path)
            metadata = processor.probe(path)
            offset = scene.media.start_offset
            length = min(metadata.duration - offset, scene.end - scene.start)
            if length <= 0:
                raise SearchyError("Imported scene starts beyond its source media duration", 422)
            identity = stable_id(
                f"{path.resolve()}:{path.stat().st_size}:{path.stat().st_mtime_ns}"
            )
            cache = (self.settings.data_dir / "processing" / "import_frames" / identity).resolve()
            frames = processor.sample_frames(path, offset, offset + length, cache)
            scene.frames = [
                f.model_copy(update={"timestamp": scene.start + f.timestamp - offset})
                for f in frames
            ]
            scene.provenance.append(
                Provenance(
                    source=str(path),
                    method="sampled_imported_clip_frames_with_inferred_episode_offset",
                )
            )
        return scenes

    def run_once(self) -> bool:
        store = self.services.metadata
        job = store.claim_job(self.owner, self.settings.job_lease_seconds)
        if not job:
            return False
        stopped = threading.Event()
        lost = threading.Event()

        def heartbeat():
            while not stopped.wait(self.settings.job_lease_seconds / 3):
                try:
                    if not store.update_job(
                        job["job_id"], self.owner, lease_seconds=self.settings.job_lease_seconds
                    ):
                        lost.set()
                        return
                except Exception:
                    lost.set()
                    return

        def progress(value: float, stage: str):
            if lost.is_set() or not store.update_job(
                job["job_id"],
                self.owner,
                progress=min(0.99, max(0, value)),
                stage=stage,
                lease_seconds=self.settings.job_lease_seconds,
            ):
                raise SearchyError(
                    "Worker lost ownership of this job; retry after its lease expires"
                )

        thread = threading.Thread(target=heartbeat, daemon=True)
        thread.start()
        try:
            result = self.process(job, progress)
            if lost.is_set():
                raise SearchyError("Worker lost ownership of this job")
            store.update_job(
                job["job_id"],
                self.owner,
                status="completed",
                progress=1,
                stage="completed",
                result=result,
            )
        except Exception as exc:
            message = (
                str(exc)
                if isinstance(exc, SearchyError)
                else (
                    f"Ingestion failed during {store.get_job(job['job_id'])['stage']} ({type(exc).__name__})"
                )
            )
            logger.error("Job %s failed (%s)", job["job_id"], type(exc).__name__)
            store.update_job(
                job["job_id"], self.owner, status="failed", stage="failed", error=message
            )
        finally:
            stopped.set()
            thread.join(timeout=2)
        return True

    def process(self, job: dict, progress) -> dict:
        svc = self.services
        payload = job["payload"]
        progress(0.01, "checking services")
        svc.graph.ensure_schema()
        svc.vectors.ensure_collection()
        stale = set()
        if job["kind"] == "import":
            root = Path(payload["root"]).resolve()
            if not root.is_relative_to(self.settings.import_root.resolve()):
                raise SearchyError("Import directory is outside configured IMPORT_ROOT", 422)
            progress(0.03, "reading processed chunks")
            imported = import_chunks(
                root,
                payload["collection_id"],
                payload.get("limit"),
                ffprobe_path=self.settings.ffprobe_path,
                episode_media_dir=self.settings.episode_media_dir,
            )
            videos, scenes, warnings = imported.videos, imported.scenes, imported.warnings
            if self.settings.visual_enabled:
                scenes = self.prepare_import_frames(scenes, progress)
        elif job["kind"] == "upload":
            path = Path(payload["path"]).resolve()
            if not path.is_relative_to((self.settings.data_dir / "uploads").resolve()):
                raise SearchyError("Upload is outside managed media storage", 422)
            video = Video(
                video_id=stable_id(f"upload:{payload['collection_id']}:{payload['digest']}"),
                collection_id=payload["collection_id"],
                title=payload["title"],
                original_id=payload["digest"],
                source_kind="upload",
                duration=payload["duration"],
                media_path=str(path),
            )
            svc.metadata.save_video(video)
            scenes = VideoProcessor(self.settings).process(
                path, video, lambda value, stage: progress(0.03 + value * 0.52, stage)
            )
            videos, warnings = [video], []
            stale = svc.metadata.scene_ids(video.video_id) - {s.scene_id for s in scenes}
        else:
            raise SearchyError("Unknown ingestion job type", 422)
        by_id = {video.video_id: video for video in videos}
        for video in videos:
            svc.metadata.save_video(video)
        pending = []
        skipped = 0
        identifiers = [scene.scene_id for scene in scenes]
        graph_ids = svc.graph.indexed_scene_ids(identifiers)
        vector_ids = svc.vectors.indexed_scene_ids(identifiers)
        for scene in scenes:
            if (
                not payload.get("force", False)
                and scene.scene_id in graph_ids
                and scene.scene_id in vector_ids
                and svc.metadata.get_scene(scene.scene_id) == scene
                and svc.metadata.is_indexed(scene.scene_id)
            ):
                skipped += 1
                continue
            svc.metadata.save_scene(scene)
            pending.append(scene)
        for offset in range(0, len(pending), 16):
            batch = pending[offset : offset + 16]
            progress(
                0.55 + 0.43 * offset / max(1, len(pending)),
                f"indexing scenes {offset + 1}-{offset + len(batch)}",
            )
            svc.graph.upsert_scenes(batch, by_id)
            svc.vectors.upsert(batch)
            for scene in batch:
                svc.metadata.mark_indexed(scene.scene_id)
        if stale:
            progress(0.99, "removing obsolete scene boundaries")
            svc.graph.delete_scenes(sorted(stale))
            svc.vectors.delete_scenes(sorted(stale))
            svc.metadata.delete_scenes(sorted(stale))
        return dict(
            videos=len(videos),
            scenes=len(scenes),
            indexed=len(pending),
            unchanged=skipped,
            warnings=warnings,
        )


def main():
    parser = argparse.ArgumentParser(description="Run Searchy's durable ingestion worker")
    parser.add_argument("--once", action="store_true", help="Process one queued job and exit")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    services = Services(Settings())
    worker = Worker(services)
    try:
        while True:
            processed = worker.run_once()
            if args.once:
                break
            if not processed:
                time.sleep(services.settings.worker_poll_seconds)
    except KeyboardInterrupt:
        pass
    finally:
        services.close()


if __name__ == "__main__":
    main()
