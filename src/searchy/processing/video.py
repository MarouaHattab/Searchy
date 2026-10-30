import hashlib
import json
import math
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from searchy.core.config import Settings
from searchy.core.errors import InvalidInput, SearchyError
from searchy.domain import Dialogue, Frame, Media, Observation, Provenance, Scene, Video, stable_id
from searchy.models.vision import get_vision_provider, registered_references


@dataclass(frozen=True)
class VideoMetadata:
    duration: float
    has_audio: bool
    width: int
    height: int


def merge_boundaries(
    cuts: list[float], duration: float, minimum: float, maximum: float
) -> list[tuple[float, float]]:
    if not 0 < minimum <= maximum or not math.isfinite(duration) or duration <= 0:
        raise InvalidInput("Scene lengths require 0 < scene_min_seconds <= scene_max_seconds")
    boundaries = [0.0]
    for cut in sorted(set(cuts)):
        if math.isfinite(cut) and boundaries[-1] + minimum <= cut < duration:
            boundaries.append(cut)
    if len(boundaries) > 1 and duration - boundaries[-1] < minimum:
        boundaries.pop()
    boundaries.append(duration)
    result = []
    for start, end in zip(boundaries, boundaries[1:], strict=False):
        count = math.ceil((end - start) / maximum)
        step = (end - start) / count
        result.extend((start + i * step, start + (i + 1) * step) for i in range(count))
    return result


def scene_dialogue(words: list[Dialogue], start: float, end: float) -> list[Dialogue]:
    result: list[Dialogue] = []
    for word in words:
        if not start <= (word.start + word.end) / 2 < end:
            continue
        clipped = word.model_copy(
            update={"start": max(start, word.start), "end": min(end, word.end)}
        )
        if result and clipped.start - result[-1].end < 1.5 and len(result[-1].text) < 400:
            result[-1] = result[-1].model_copy(
                update={
                    "text": f"{result[-1].text} {clipped.text}",
                    "end": clipped.end,
                }
            )
        else:
            result.append(clipped)
    return result


def _fingerprint(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:20]


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_json(path: Path, data: object):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data), encoding="utf-8")
    temporary.replace(path)


class VideoProcessor:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._whisper = None

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

    def _detect_scenes(self, path: Path, duration: float, cache: Path) -> list[tuple[float, float]]:
        cached = _read_json(cache / "shots-v1.json")
        if cached is None:
            try:
                from scenedetect import ContentDetector, detect
            except ImportError:
                raise SearchyError("Shot detection requires: uv sync --extra video") from None
            try:
                shots = detect(
                    str(path), ContentDetector(), show_progress=False, start_in_scene=True
                )
                cached = [shot[1].get_seconds() for shot in shots[:-1]]
            except Exception:
                raise SearchyError("PySceneDetect could not decode the uploaded video") from None
            _write_json(cache / "shots-v1.json", cached)
        try:
            return merge_boundaries(
                [float(cut) for cut in cached],
                duration,
                self.settings.scene_min_seconds,
                self.settings.scene_max_seconds,
            )
        except (ValueError, TypeError):
            raise SearchyError(
                "Cached shot boundaries are invalid; remove the processing cache and retry"
            ) from None

    def _transcribe(self, path: Path, metadata: VideoMetadata, cache: Path) -> list[Dialogue]:
        if not metadata.has_audio:
            return []
        signature = _fingerprint(
            [
                "whisper-words-v2",
                self.settings.whisper_model_id,
                self.settings.whisper_device,
                self.settings.whisper_compute_type,
            ]
        )
        transcript_path = cache / f"transcript-{signature}.json"
        cached = _read_json(transcript_path)
        if cached is not None:
            try:
                return TypeAdapter(list[Dialogue]).validate_python(cached)
            except ValidationError:
                raise SearchyError(
                    "Cached transcript is invalid; remove the processing cache and retry"
                ) from None
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            raise SearchyError("Speech transcription requires: uv sync --extra video") from None
        audio_path = cache / "audio.wav"
        if not audio_path.is_file():
            pending_audio = cache / "audio.pending.wav"
            self._run(
                [
                    self.settings.ffmpeg_path,
                    "-nostdin",
                    "-v",
                    "error",
                    "-i",
                    str(path),
                    "-vn",
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    "-c:a",
                    "pcm_s16le",
                    "-y",
                    str(pending_audio),
                ],
                "FFmpeg audio extraction",
                max(60, metadata.duration * 2),
            )
            pending_audio.replace(audio_path)
        try:
            if self._whisper is None:
                self._whisper = WhisperModel(
                    self.settings.whisper_model_id,
                    device=self.settings.whisper_device,
                    compute_type=self.settings.whisper_compute_type,
                    download_root=str((self.settings.model_cache_dir / "whisper").resolve()),
                    use_auth_token=self.settings.hf_token.get_secret_value() or None,
                )
            segments, _ = self._whisper.transcribe(
                str(audio_path), beam_size=5, vad_filter=True, word_timestamps=True
            )
            dialogue = []
            for segment in segments:
                for word in segment.words or []:
                    start = max(0.0, float(word.start))
                    end = min(metadata.duration, float(word.end))
                    if end > start and word.word.strip():
                        dialogue.append(
                            Dialogue(
                                start=start,
                                end=end,
                                text=word.word.strip(),
                                provenance=Provenance(
                                    source=str(audio_path),
                                    method="speech_transcription_word_timestamps",
                                    model=self.settings.whisper_model_id,
                                    confidence=word.probability,
                                ),
                            )
                        )
        except Exception:
            raise SearchyError(
                "Whisper transcription failed. Check model download access, device and compute type."
            ) from None
        _write_json(transcript_path, [item.model_dump(mode="json") for item in dialogue])
        return dialogue

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

    def process(
        self, path: Path, video: Video, progress: Callable[[float, str], None]
    ) -> list[Scene]:
        path = path.resolve()
        progress(0.02, "validating video")
        metadata = self.probe(path)
        references = registered_references(self.settings, video)
        provider = get_vision_provider(self.settings, references=references)
        self._run([self.settings.ffmpeg_path, "-version"], "FFmpeg", 10)
        content_hash = hashlib.sha256()
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                content_hash.update(chunk)
        cache = (self.settings.data_dir / "processing" / content_hash.hexdigest()).resolve()
        cache.mkdir(parents=True, exist_ok=True)
        progress(0.05, "detecting shot boundaries")
        intervals = self._detect_scenes(path, metadata.duration, cache)
        progress(0.15, "transcribing speech" if metadata.has_audio else "video has no audio stream")
        dialogue = self._transcribe(path, metadata, cache)
        reference_signature = [
            (
                reference.character_id,
                reference.name,
                reference.revision,
                hashlib.sha256(reference.path.read_bytes()).hexdigest(),
            )
            for reference in references
        ]
        scenes = []
        for index, (start, end) in enumerate(intervals):
            progress(
                0.3 + 0.65 * index / len(intervals), f"analyzing scene {index + 1}/{len(intervals)}"
            )
            frames = self.sample_frames(path, start, end, cache)
            scene_speech = scene_dialogue(dialogue, start, end)
            signature = _fingerprint(
                [
                    "vision-v3-scoped-identities",
                    self.settings.llm_provider,
                    self.settings.llm_model_id,
                    self.settings.vlm_max_images,
                    reference_signature,
                    [frame.timestamp for frame in frames],
                    [item.model_dump(mode="json") for item in scene_speech],
                ]
            )
            analysis_path = cache / f"analysis-{signature}.json"
            analysis = _read_json(analysis_path)
            if analysis is None:
                description, observations = provider.analyze(frames, scene_speech, start, end)
                analysis = {
                    "description": description,
                    "observations": [item.model_dump(mode="json") for item in observations],
                }
                _write_json(analysis_path, analysis)
            try:
                observations = TypeAdapter(list[Observation]).validate_python(
                    analysis["observations"]
                )
                scene = Scene(
                    scene_id=stable_id(f"{video.video_id}:scene:{start:.6f}:{end:.6f}"),
                    video_id=video.video_id,
                    collection_id=video.collection_id,
                    start=start,
                    end=end,
                    timestamp_basis="source_media_seconds",
                    description=analysis["description"],
                    dialogue=scene_speech,
                    observations=observations,
                    frames=frames,
                    media=Media(path=str(path), start_offset=start, duration=metadata.duration),
                    provenance=[
                        Provenance(source=str(path), method="shot_detection_and_frame_sampling")
                    ],
                )
            except (ValidationError, KeyError, TypeError):
                raise SearchyError("Cached visual analysis contains invalid evidence") from None
            scenes.append(scene)
        progress(0.97, "scene extraction complete")
        return scenes
