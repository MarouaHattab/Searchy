import hashlib
import html
import subprocess
import threading
from pathlib import Path
from uuid import uuid4

from searchy.core.config import Settings
from searchy.core.errors import SearchyError
from searchy.domain import Scene

_thumbnail_lock = threading.Lock()


def _timestamp(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    seconds, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02}.{milliseconds:03}"


class MediaService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def _source(self, scene: Scene) -> Path:
        if not scene.media or not Path(scene.media.path).is_file():
            raise SearchyError("Source media is unavailable; metadata remains searchable", 404)
        return Path(scene.media.path).resolve()

    def thumbnail(self, scene: Scene) -> Path:
        source = self._source(scene)
        for frame in scene.frames:
            path = Path(frame.path)
            in_scene = scene.start is None or scene.start <= frame.timestamp <= scene.end
            if in_scene and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
                if path.is_file() and path.stat().st_size:
                    return path

        offset = scene.media.start_offset
        sample_seconds = min(3, (scene.end - scene.start) / 2) if scene.start is not None else 3
        offset += sample_seconds
        if scene.media.duration is not None:
            offset = min(offset, max(0, scene.media.duration - 0.05))
        try:
            stat = source.stat()
            signature = f"{source}:{stat.st_mtime_ns}:{stat.st_size}:{offset:.6f}"
            identifier = hashlib.sha256(signature.encode()).hexdigest()
            directory = self.settings.data_dir / "thumbnails"
            destination = directory / f"{identifier}.jpg"
            with _thumbnail_lock:
                directory.mkdir(parents=True, exist_ok=True)
                if destination.is_file() and destination.stat().st_size:
                    return destination
                pending = directory / f"{identifier}.{uuid4().hex}.pending.jpg"
                try:
                    subprocess.run(
                        [
                            self.settings.ffmpeg_path,
                            "-nostdin",
                            "-v",
                            "error",
                            "-ss",
                            f"{offset:.6f}",
                            "-i",
                            str(source),
                            "-frames:v",
                            "1",
                            "-vf",
                            "scale=640:-2",
                            "-q:v",
                            "3",
                            "-y",
                            str(pending),
                        ],
                        check=True,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=20,
                    )
                    if not pending.is_file() or pending.stat().st_size == 0:
                        raise SearchyError("No thumbnail could be extracted from this video", 422)
                    pending.replace(destination)
                except FileNotFoundError:
                    raise SearchyError(
                        "FFmpeg is unavailable; configure FFMPEG_PATH", 503
                    ) from None
                except subprocess.TimeoutExpired:
                    raise SearchyError("Thumbnail extraction timed out; try again", 503) from None
                except subprocess.CalledProcessError:
                    raise SearchyError(
                        "A thumbnail could not be extracted from this video", 422
                    ) from None
                finally:
                    pending.unlink(missing_ok=True)
            return destination
        except OSError:
            raise SearchyError("Thumbnail storage is unavailable", 503) from None

    def subtitles(self, scene: Scene) -> str:
        self._source(scene)
        if not scene.dialogue:
            return "WEBVTT\n\n"
        if scene.start is None:
            raise SearchyError("Subtitle timing is unavailable for this scene", 422)
        cues = []
        for line in sorted(scene.dialogue, key=lambda item: item.start):
            start = max(0, line.start - scene.start + scene.media.start_offset)
            end = line.end - scene.start + scene.media.start_offset
            if scene.media.duration is not None:
                end = min(end, scene.media.duration)
            if round(end * 1000) <= round(start * 1000):
                continue
            text = "\n".join(part.strip() for part in line.text.splitlines() if part.strip())
            if text:
                cues.append(
                    f"{_timestamp(start)} --> {_timestamp(end)}\n{html.escape(text, quote=False)}"
                )
        return "WEBVTT\n\n" + "\n\n".join(cues) + ("\n\n" if cues else "")
