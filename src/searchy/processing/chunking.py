import argparse
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from searchy.core import InvalidInput, SearchyError, Settings

VIDEO_SUFFIXES = {".mp4", ".mkv", ".mov", ".avi", ".m4v", ".webm"}
SUBTITLE_SUFFIXES = (".vtt", ".srt")

DEFAULT_CHUNK_SECONDS = 60
CHUNK_DIGITS = 5


@dataclass(frozen=True)
class Subtitle:
    start: float
    end: float
    text: str


@dataclass
class Chunk:
    index: int
    folder: Path
    media: Path
    start: float
    end: float

    @property
    def name(self) -> str:
        return self.folder.name


@dataclass
class EpisodeResult:
    episode: str
    folder: Path
    chunks: list[Chunk] = field(default_factory=list)
    subtitle_source: str | None = None
    warnings: list[str] = field(default_factory=list)


def _run(args: list[str], label: str, timeout: float = 300) -> str:
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
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "").strip().splitlines()
        reason = f": {detail[-1]}" if detail else ""
        raise SearchyError(f"{label} failed{reason}") from None


def probe_duration(path: Path, ffprobe_path: str = "ffprobe") -> float:
    if not path.is_file() or path.stat().st_size == 0:
        raise InvalidInput(f"Media file is missing or empty: {path}")
    raw = _run(
        [
            ffprobe_path,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path.resolve()),
        ],
        "FFprobe",
        60,
    )
    try:
        duration = float(raw.strip())
    except ValueError:
        raise InvalidInput(f"FFprobe returned no duration for {path.name}") from None
    if not duration > 0:
        raise InvalidInput(f"Media file has no positive duration: {path.name}")
    return duration


def _timestamp(value: str) -> float:
    cleaned = value.strip().replace(",", ".")
    parts = cleaned.split(":")
    if len(parts) != 3:
        raise ValueError(f"unsupported timestamp {value!r}")
    hours, minutes, seconds = parts
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def parse_subtitles(text: str) -> list[Subtitle]:
    cues: list[Subtitle] = []
    for block in text.replace("\r\n", "\n").replace("\r", "\n").split("\n\n"):
        lines = [line for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        for position, line in enumerate(lines):
            if "-->" not in line:
                continue
            try:
                left, _, right = line.partition("-->")
                start = _timestamp(left)
                end = _timestamp(right.strip().split()[0])
            except (ValueError, IndexError):
                break
            body = " ".join(part.strip() for part in lines[position + 1 :] if part.strip())
            if body and end > start:
                cues.append(Subtitle(start=start, end=end, text=body))
            break
    return sorted(cues, key=lambda cue: (cue.start, cue.end))


def read_subtitle_file(path: Path) -> list[Subtitle]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise InvalidInput(f"Cannot read subtitle file {path.name}: {exc}") from None
    cues = parse_subtitles(text)
    if not cues:
        raise InvalidInput(f"No usable cues found in subtitle file {path.name}")
    return cues


def find_subtitle_file(episode_stem: str, subtitles_folder: Path | None) -> Path | None:
    if subtitles_folder is None or not subtitles_folder.is_dir():
        return None
    for suffix in SUBTITLE_SUFFIXES:
        candidate = subtitles_folder / f"{episode_stem.strip()}{suffix}"
        if candidate.is_file():
            return candidate
    return None


def has_audio(path: Path, ffprobe_path: str = "ffprobe") -> bool:
    raw = _run(
        [
            ffprobe_path,
            "-v",
            "error",
            "-select_streams",
            "a",
            "-show_entries",
            "stream=index",
            "-of",
            "csv=p=0",
            str(path.resolve()),
        ],
        "FFprobe",
        60,
    )
    return bool(raw.strip())


def transcribe(path: Path, settings: Settings) -> list[Subtitle]:
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise SearchyError(
            "Speech transcription requires: uv sync --extra video"
        ) from None
    try:
        model = WhisperModel(
            settings.whisper_model_id,
            device=settings.whisper_device,
            compute_type=settings.whisper_compute_type,
            download_root=str((settings.model_cache_dir / "whisper").resolve()),
            use_auth_token=settings.hf_token.get_secret_value() or None,
        )
    except Exception:
        raise SearchyError(
            "Whisper model could not be loaded. Check model access, device and compute type."
        ) from None
    try:
        segments, _ = model.transcribe(str(path), beam_size=5, vad_filter=True)
        cues = []
        for segment in segments:
            text = segment.text.strip()
            if text and segment.end > segment.start:
                cues.append(
                    Subtitle(start=float(segment.start), end=float(segment.end), text=text)
                )
    except IndexError:
        return []
    except Exception as exc:
        raise SearchyError(f"Whisper transcription failed: {exc}") from None
    return cues


def subtitles_in_range(
    subtitles: list[Subtitle], start: float, end: float
) -> tuple[list[dict], list[str]]:
    with_time: list[dict] = []
    without_time: list[str] = []
    for cue in subtitles:
        if cue.start < end and cue.end > start:
            with_time.append({"start": cue.start, "end": cue.end, "text": cue.text})
            without_time.append(cue.text)
    return with_time, without_time


def chunk_folder_name(index: int) -> str:
    return f"chunk_{index + 1:0{CHUNK_DIGITS}d}"


def split_media(
    path: Path,
    index: int,
    start: float,
    end: float,
    output_folder: Path,
    ffmpeg_path: str = "ffmpeg",
) -> Chunk:
    folder = output_folder / chunk_folder_name(index)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{index + 1:0{CHUNK_DIGITS}d}{path.suffix.lower()}"
    pending = target.with_name(f"{target.stem}.pending{target.suffix}")
    _run(
        [
            ffmpeg_path,
            "-nostdin",
            "-v",
            "error",
            "-ss",
            f"{start:.6f}",
            "-i",
            str(path.resolve()),
            "-t",
            f"{end - start:.6f}",
            "-c",
            "copy",
            "-avoid_negative_ts",
            "1",
            "-y",
            str(pending),
        ],
        "FFmpeg chunk split",
    )
    if not pending.is_file() or pending.stat().st_size == 0:
        raise SearchyError(f"FFmpeg produced no output for chunk {index + 1}")
    pending.replace(target)
    return Chunk(index=index, folder=folder, media=target, start=start, end=end)


def write_chunk_subtitles(folder: Path, with_time: list[dict], without_time: list[str]) -> Path:
    path = folder / "subtitles.json"
    pending = path.with_suffix(".pending.json")
    pending.write_text(
        json.dumps(
            {
                "subtitles_with_timestamps": with_time,
                "subtitles_without_timestamps": without_time,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    pending.replace(path)
    return path


def process_episode(
    video_path: Path,
    output_folder: Path,
    settings: Settings,
    subtitle_path: Path | None = None,
    chunk_seconds: int = DEFAULT_CHUNK_SECONDS,
    force: bool = False,
) -> EpisodeResult:
    if chunk_seconds != DEFAULT_CHUNK_SECONDS:
        raise InvalidInput(
            f"Chunk length must be {DEFAULT_CHUNK_SECONDS} seconds; "
            "ingestion/importer.py reconstructs timestamps from that value"
        )
    if video_path.suffix.lower() not in VIDEO_SUFFIXES:
        raise InvalidInput(f"Unsupported video extension for {video_path.name}")
    duration = probe_duration(video_path, settings.ffprobe_path)
    result = EpisodeResult(episode=output_folder.name, folder=output_folder)
    output_folder.mkdir(parents=True, exist_ok=True)

    count = int(duration // chunk_seconds)
    if duration % chunk_seconds:
        count += 1

    subtitles: list[Subtitle] | None = None

    def cues() -> list[Subtitle]:
        nonlocal subtitles
        if subtitles is None:
            if subtitle_path is not None:
                result.subtitle_source = str(subtitle_path)
                subtitles = read_subtitle_file(subtitle_path)
            elif not has_audio(video_path, settings.ffprobe_path):
                subtitles = []
                result.subtitle_source = None
            else:
                result.subtitle_source = "whisper"
                subtitles = transcribe(video_path, settings)
            if not subtitles:
                result.warnings.append("No subtitles were produced; chunks carry media only")
        return subtitles

    for index in range(count):
        start = index * chunk_seconds
        end = min(start + chunk_seconds, duration)
        folder = output_folder / chunk_folder_name(index)
        existing = (
            sorted(
                child
                for child in folder.iterdir()
                if child.is_file() and child.suffix.lower() in VIDEO_SUFFIXES
            )
            if folder.is_dir()
            else []
        )
        if existing and (folder / "subtitles.json").is_file() and not force:
            result.chunks.append(
                Chunk(index=index, folder=folder, media=existing[0], start=start, end=end)
            )
            continue
        try:
            chunk = split_media(
                video_path, index, start, end, output_folder, settings.ffmpeg_path
            )
        except SearchyError as exc:
            result.warnings.append(f"Chunk {index + 1} could not be split: {exc}")
            continue
        with_time, without_time = subtitles_in_range(cues(), start, end)
        write_chunk_subtitles(chunk.folder, with_time, without_time)
        result.chunks.append(chunk)
    return result


def process_collection(
    episodes_folder: Path,
    output_base_folder: Path,
    settings: Settings,
    subtitles_folder: Path | None = None,
    chunk_seconds: int = DEFAULT_CHUNK_SECONDS,
    limit: int | None = None,
    force: bool = False,
) -> list[EpisodeResult]:
    if not episodes_folder.is_dir():
        raise InvalidInput(f"Episodes folder does not exist: {episodes_folder}")
    if limit is not None and limit < 1:
        raise InvalidInput("Limit must be at least 1")
    videos = sorted(
        path
        for path in episodes_folder.iterdir()
        if path.is_file() and not path.is_symlink() and path.suffix.lower() in VIDEO_SUFFIXES
    )
    if limit is not None:
        videos = videos[:limit]
    if not videos:
        raise InvalidInput(f"No video files found in {episodes_folder}")

    results: list[EpisodeResult] = []
    for video in videos:
        try:
            results.append(
                process_episode(
                    video,
                    output_base_folder / video.stem,
                    settings,
                    find_subtitle_file(video.stem, subtitles_folder),
                    chunk_seconds,
                    force,
                )
            )
        except SearchyError as exc:
            failed = EpisodeResult(episode=video.stem, folder=output_base_folder / video.stem)
            failed.warnings.append(str(exc))
            results.append(failed)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Split source episodes into the chunked dataset layout Searchy imports"
    )
    parser.add_argument("episodes", type=Path, help="Folder containing source episode videos")
    parser.add_argument(
        "--subtitles", type=Path, default=None, help="Folder containing .vtt or .srt files"
    )
    parser.add_argument(
        "--output", type=Path, default=None, help="Output root (default IMport_ROOT)"
    )
    parser.add_argument("--chunk-seconds", type=int, default=DEFAULT_CHUNK_SECONDS)
    parser.add_argument("--limit", type=int, default=None, help="Process at most N episodes")
    parser.add_argument("--force", action="store_true", help="Re-split chunks that already exist")
    args = parser.parse_args()

    settings = Settings()
    output = args.output or settings.import_root
    results = process_collection(
        args.episodes,
        output,
        settings,
        args.subtitles,
        args.chunk_seconds,
        args.limit,
        args.force,
    )
    for result in results:
        state = f"{len(result.chunks)} chunks"
        if result.subtitle_source:
            state += f", subtitles from {Path(result.subtitle_source).name}"
        print(f"{result.episode}: {state}")
        for warning in result.warnings:
            print(f"  warning: {warning}")
    total = sum(len(result.chunks) for result in results)
    failed = sum(1 for result in results if not result.chunks)
    print(f"Done: {len(results) - failed} episodes, {total} chunks, {failed} failed")


if __name__ == "__main__":
    main()
