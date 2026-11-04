import argparse
import logging
import shutil
import threading
from pathlib import Path
from uuid import uuid4

from searchy.core.config import Settings
from searchy.core.errors import SearchyError
from searchy.domain import (
    Media,
    Observation,
    ObservationKind,
    Provenance,
    Scene,
    Video,
    stable_id,
)
from searchy.ingestion.importer import import_chunks
from searchy.processing.video import VideoProcessor
from searchy.services.container import Services

logger = logging.getLogger("searchy.worker")


class Worker:
    def __init__(self, services):
        self.services = services
        self.settings = services.settings
        self.owner = str(uuid4())

    def prepare_upload(self, payload: dict, progress) -> tuple[list[Video], list[Scene], list[str]]:
        from searchy.processing import captioning, chunking

        path = Path(payload["path"]).resolve()
        uploads = (self.settings.data_dir / "uploads").resolve()
        if not path.is_relative_to(uploads):
            raise SearchyError("Upload is outside managed media storage", 422)

        title = Path(payload.get("title") or path.name).stem.strip() or path.stem
        prepared_root = (self.settings.data_dir / "prepared").resolve()
        episode_dir = prepared_root / title
        dataset_root = prepared_root / f"{title}__dataset"

        progress(0.03, "splitting video into chunks")
        subtitles = self._find_upload_subtitles(payload, uploads)
        chunked = chunking.process_episode(
            path,
            episode_dir,
            self.settings,
            subtitles,
            force=bool(payload.get("force")),
        )

        progress(0.30, f"captioning {len(chunked.chunks)} chunks")
        captioner = captioning.build_captioner(
            self.settings,
            self.settings.caption_backend,
            self.settings.caption_model_id or None,
            None,
        )
        # Only people registered for this collection may be named. Sending the
        # shared portrait folder made the model attribute familiar names to
        # unrelated footage.
        captioner.references = captioning.collection_references(
            self.settings, payload["collection_id"]
        )
        captioned = captioning.process_episode(episode_dir, captioner)
        warnings = [*chunked.warnings, *captioned.warnings]

        progress(0.75, "reading prepared chunks")
        if dataset_root.exists():
            shutil.rmtree(dataset_root, ignore_errors=True)
        import_base = (dataset_root / "episodes_splitted").resolve()
        import_base.mkdir(parents=True, exist_ok=True)
        shutil.move(str(episode_dir), str(import_base / title))
        imported = import_chunks(
            import_base,
            payload["collection_id"],
            None,
            ffprobe_path=self.settings.ffprobe_path,
            episode_media_dir=None,
        )
        videos, scenes = imported.videos, imported.scenes
        warnings.extend(imported.warnings)
        if self.settings.visual_enabled:
            scenes = self.prepare_import_frames(scenes, progress)
        if not payload.get("keep_prepared"):
            shutil.rmtree(dataset_root, ignore_errors=True)

        # Derived clips live under the throwaway dataset, which is deleted below
        # unless it was asked for. Playback therefore has to point at the stored
        # upload, keeping the chunk's offset so a scene still starts where it is.
        duration = payload.get("duration")
        for scene in scenes:
            offset = scene.media.start_offset if scene.media else (scene.start or 0.0)
            scene.media = Media(path=str(path), start_offset=offset, duration=duration)
        return videos, scenes, warnings

    def _find_upload_subtitles(self, payload: dict, uploads: Path) -> Path | None:
        candidate = payload.get("subtitles_path")
        if not candidate:
            return None
        path = Path(candidate).resolve()
        if not path.is_relative_to(uploads) or not path.is_file():
            raise SearchyError("Uploaded subtitle file is missing or outside managed storage", 422)
        return path

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

    def preserve_registered_evidence(self, scene: Scene, previous: Scene | None) -> Scene:
        if (
            previous is None
            or scene.start is None
            or any(
                getattr(previous, field) != getattr(scene, field)
                for field in (
                    "scene_id",
                    "video_id",
                    "collection_id",
                    "episode_id",
                    "source_chunk",
                    "start",
                    "end",
                )
            )
        ):
            return scene
        scene = scene.model_copy(deep=True)
        frame_keys = {(str(Path(frame.path).resolve()), frame.timestamp) for frame in scene.frames}
        for frame in previous.frames:
            path = Path(frame.path)
            key = (str(path.resolve()), frame.timestamp)
            if (
                key not in frame_keys
                and scene.start <= frame.timestamp <= scene.end
                and not path.is_symlink()
                and path.is_file()
                and path.stat().st_size > 0
            ):
                scene.frames.append(frame.model_copy())
                frame_keys.add(key)
        characters = getattr(self.services, "characters", None)
        registry = getattr(characters, "store", None)
        if registry is None:
            return scene
        registered = {
            character["id"]: character
            for character in registry.list(scene.collection_id, scene.video_id)
        }

        def evidence_key(observation: Observation) -> tuple:
            return (
                observation.kind,
                None if observation.kind == ObservationKind.CHARACTER else observation.value,
                observation.evidence,
                observation.start,
                observation.end,
                observation.provenance.source,
                observation.provenance.method,
                observation.provenance.model,
            )

        recognition_methods = {
            "sface_reference_comparison",
            "vlm_reference_comparison",
            "human_reviewed_character_match",
        }
        recognition = getattr(self.services, "recognition", None)
        recorded_matches: dict[str, list[dict]] = {}

        def valid_recognition(observation: Observation) -> bool:
            if recognition is None:
                return True
            identifier = observation.character_id
            if identifier not in registered:
                return False
            if identifier not in recorded_matches:
                recorded_matches[identifier] = recognition._rows(
                    identifier, scene.scene_id, registered[identifier]["revision"]
                )
            for match in recorded_matches[identifier]:
                reviewed = observation.provenance.method == "human_reviewed_character_match"
                if (
                    match["timestamp"] != observation.start
                    or match["evidence"] != observation.evidence
                    or match["model_id"] != observation.provenance.model
                    or (reviewed and match["status"] != "accepted")
                    or (
                        not reviewed
                        and (
                            match["status"] != "pending"
                            or not match["qualified"]
                            or match["method"] != observation.provenance.method
                        )
                    )
                ):
                    continue
                try:
                    if (
                        recognition.frame_path(identifier, match["id"]).resolve()
                        == Path(observation.provenance.source).resolve()
                    ):
                        return True
                except SearchyError:
                    continue
            return False

        for observation in previous.observations:
            identifiers = {
                identifier
                for identifier in (observation.character_id, observation.subject_id)
                if identifier
            }
            if not identifiers or not identifiers.issubset(registered):
                continue
            source = Path(observation.provenance.source)
            frame_valid = (
                observation.start is not None
                and any(
                    path == str(source.resolve())
                    and observation.start <= timestamp <= observation.end
                    for path, timestamp in frame_keys
                )
                and source.is_file()
                and not source.is_symlink()
                and source.stat().st_size > 0
            )
            if (
                observation.provenance.method in recognition_methods | {"sampled_frame_vlm"}
                and not frame_valid
            ):
                continue
            if observation.provenance.method in recognition_methods and not valid_recognition(
                observation
            ):
                continue
            candidates = [
                item
                for item in scene.observations
                if evidence_key(item) == evidence_key(observation)
            ]
            if len(candidates) == 1 and observation.provenance.method not in recognition_methods:
                target = candidates[0]
                if any(
                    getattr(target, field) not in {None, getattr(observation, field)}
                    for field in ("character_id", "subject_id")
                    if getattr(observation, field)
                ):
                    continue
                for field, label in (("character_id", "value"), ("subject_id", "subject")):
                    identifier = getattr(observation, field)
                    if identifier:
                        setattr(target, field, identifier)
                        setattr(target, label, registered[identifier]["name"])
                if observation.provenance.verified:
                    target.provenance = observation.provenance.model_copy()
                continue
            if not frame_valid:
                continue
            retained = observation.model_copy(deep=True)
            if retained.character_id:
                retained.value = registered[retained.character_id]["name"]
            if retained.subject_id:
                retained.subject = registered[retained.subject_id]["name"]
            if retained not in scene.observations:
                scene.observations.append(retained)
        for line in scene.dialogue:
            candidates = [
                old
                for old in previous.dialogue
                if old.speaker_id in registered
                and (old.start, old.end, old.text) == (line.start, line.end, line.text)
            ]
            if len(candidates) == 1 and line.speaker_id in {None, candidates[0].speaker_id}:
                old = candidates[0]
                line.speaker_id = old.speaker_id
                line.speaker = registered[old.speaker_id]["name"]
                if old.provenance and old.provenance.verified:
                    line.provenance = old.provenance.model_copy()
        return scene

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

    def run_forever(self, stop_event: threading.Event) -> None:
        while not stop_event.is_set():
            try:
                processed = self.run_once()
            except Exception:
                logger.exception("Worker cycle failed")
                processed = False
            if not processed:
                stop_event.wait(self.settings.worker_poll_seconds)

    def process(self, job: dict, progress) -> dict:
        svc = self.services
        payload = job["payload"]
        if job["kind"] == "character_references":
            progress(0.05, "validating character references")
            prepared = svc.characters.prepare_references(
                payload["character_id"], payload["revision"]
            )
            if prepared.get("accepted"):
                progress(0.9, "queueing appearance recognition")
                svc.recognition.start(prepared["character_id"])
                prepared = {**prepared, "recognition_queued": True}
            return prepared
        if job["kind"] == "character_recognition":
            return svc.recognition.process(payload["character_id"], payload["revision"], progress)
        if job["kind"] == "character_identity_sync":
            character = svc.characters.store.get(payload["character_id"])
            if character is None or character["revision"] != payload["revision"]:
                return {"skipped": True, "reason": "Character changed"}
            progress(0.1, "updating character identity indexes")
            return svc.recognition.sync_identity(payload["character_id"])
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
            videos, scenes, warnings = self.prepare_upload(payload, progress)
            stale = {
                scene_id
                for video in videos
                for scene_id in svc.metadata.scene_ids(video.video_id)
            } - {scene.scene_id for scene in scenes}
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
            previous = svc.metadata.get_scene(scene.scene_id)
            if job["kind"] == "import":
                scene = self.preserve_registered_evidence(scene, previous)
            if (
                not payload.get("force", False)
                and scene.scene_id in graph_ids
                and scene.scene_id in vector_ids
                and previous == scene
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
            video_ids=[video.video_id for video in videos],
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
        if args.once:
            worker.run_once()
        else:
            worker.run_forever(threading.Event())
    except KeyboardInterrupt:
        pass
    finally:
        services.close()


if __name__ == "__main__":
    main()
