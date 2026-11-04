import json
import math
import subprocess
from dataclasses import dataclass
from pathlib import Path

from searchy.core.config import Settings
from searchy.core.errors import InvalidInput, SearchyError
from searchy.domain import Frame


@dataclass(frozen=True)
class VideoMetadata:
    duration: float
    has_audio: bool
    width: int
    height: int


class VideoProcessor:
    def __init__(self, settings: Settings):
        self.settings = settings

    def _run(self, args: list[str], label: str, timeout: float = 60) -> str:
        try:
            return subprocess.run(
                args,
                capture_output=True,
                text=True,
                check=True,
                timeout=timeout,
                encoding="utf-8",
                errors="replace",
            ).stdout
        except FileNotFoundError:
            raise SearchyError(
                f"{label} is unavailable. Install FFmpeg and set FFMPEG_PATH/FFPROBE_PATH."
            ) from None
        except subprocess.TimeoutExpired:
            raise SearchyError(f"{label} exceeded the processing time limit") from None
        except subprocess.CalledProcessError:
            raise InvalidInput(
                f"{label} could not decode this video. Check its container and codecs."
            ) from None

    def probe(self, path: Path) -> VideoMetadata:
        if not path.is_file():
            raise InvalidInput("Video file is missing")
        if path.suffix.lower() not in {".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v"}:
            raise InvalidInput("Unsupported video file extension")
        if not 0 < path.stat().st_size <= self.settings.max_upload_mb * 1024 * 1024:
            raise InvalidInput(
                f"Video file must be between 1 byte and {self.settings.max_upload_mb} MB"
            )
        raw = self._run(
            [
                self.settings.ffprobe_path,
                "-v",
                "error",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(path.resolve()),
            ],
            "FFprobe",
            30,
        )
        try:
            metadata = json.loads(raw)
            streams = metadata["streams"]
            stream = next(stream for stream in streams if stream.get("codec_type") == "video")
            container = metadata["format"]["format_name"].split(",")
            if not set(container) & {"mov", "mp4", "matroska", "webm", "avi", "m4v"}:
                raise ValueError
            duration = float(metadata["format"].get("duration", stream.get("duration", 0)))
            width, height = int(stream["width"]), int(stream["height"])
            if not math.isfinite(duration) or duration <= 0 or width <= 0 or height <= 0:
                raise ValueError
        except (ValueError, KeyError, StopIteration, TypeError):
            raise InvalidInput(
                "Video requires a supported container, video stream and valid duration"
            ) from None
        if duration > self.settings.max_video_seconds:
            raise InvalidInput(f"Video exceeds MAX_VIDEO_SECONDS={self.settings.max_video_seconds}")
        return VideoMetadata(
            duration, any(s.get("codec_type") == "audio" for s in streams), width, height
        )

    def sample_frames(self, path: Path, start: float, end: float, cache: Path) -> list[Frame]:
        cache.mkdir(parents=True, exist_ok=True)
        frames = []
        for index in range(self.settings.frames_per_scene):
            timestamp = start + (end - start) * (index + 1) / (self.settings.frames_per_scene + 1)
            frame_path = cache / f"frame-{timestamp:.6f}.jpg"
            if not frame_path.is_file() or frame_path.stat().st_size == 0:
                pending_frame = frame_path.with_suffix(".pending.jpg")
                self._run(
                    [
                        self.settings.ffmpeg_path,
                        "-nostdin",
                        "-v",
                        "error",
                        "-ss",
                        f"{timestamp:.6f}",
                        "-i",
                        str(path),
                        "-frames:v",
                        "1",
                        "-vf",
                        "scale=768:768:force_original_aspect_ratio=decrease",
                        "-q:v",
                        "3",
                        "-y",
                        str(pending_frame),
                    ],
                    "FFmpeg frame extraction",
                )
                if not pending_frame.is_file() or pending_frame.stat().st_size == 0:
                    raise SearchyError("FFmpeg did not produce a representative frame")
                pending_frame.replace(frame_path)
            if not frame_path.is_file() or frame_path.stat().st_size == 0:
                raise SearchyError("FFmpeg did not produce a representative frame")
            frames.append(Frame(path=str(frame_path), timestamp=timestamp))
        return frames
