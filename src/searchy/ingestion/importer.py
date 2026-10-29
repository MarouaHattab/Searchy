import json
import math
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from searchy.core.errors import InvalidInput
from searchy.domain import (
    Dialogue,
    Media,
    Observation,
    ObservationKind,
    Provenance,
    Scene,
    Video,
    stable_id,
)

VIDEO_SUFFIXES = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v"}
CHUNK_NAME = re.compile(r"chunk_(\d+)$")
HEADINGS = {
    "SCENE SETTING",
    "CHARACTERS PRESENT",
    "ACTIONS AND INTERACTIONS",
    "OBJECTS AND PROPS",
    "DIALOGUE CONTEXT",
    "TEMPORAL NOTES",
}
GARMENTS = re.compile(
    r"\b(shirt|sweater|top|jacket|jeans|pants|trousers|dress|skirt|blazer|cardigan|coat|vest|"
    r"overalls|hoodie|suit|shorts|tie|hat|apron|robe|blouse|sleeves|scarf|shoes|boots|pajamas)\b",
    re.IGNORECASE,
)


@dataclass
class ImportResult:
    videos: list[Video] = field(default_factory=list)
    scenes: list[Scene] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _read_json(path: Path, warnings: list[str]) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            raise ValueError("expected a JSON object")
        return data
    except (OSError, ValueError) as exc:
        warnings.append(f"Ignored invalid metadata at {path}: {exc}")
        return {}


def _episodes(root: Path) -> list[Path]:
    if not root.is_dir():
        raise InvalidInput(f"Import directory does not exist: {root}")
    if (root / "episodes_splitted").is_dir():
        root = root / "episodes_splitted"
    if (root / "all_captions.json").is_file() or any(root.glob("chunk_*")):
        return [root]
    return sorted(
        p
        for p in root.iterdir()
        if p.is_dir()
        and not p.is_symlink()
        and ((p / "all_captions.json").is_file() or any(p.glob("chunk_*")))
    )


def _chunk_names(episode: Path, aggregate: dict) -> list[str]:
    names = {p.name for p in episode.iterdir() if p.is_dir() and not p.is_symlink()}
    names.update(aggregate)
    return sorted(
        (n for n in names if CHUNK_NAME.fullmatch(n) and int(n[6:]) > 0), key=lambda n: int(n[6:])
    )


def _media_files(chunk: Path) -> list[Path]:
    if not chunk.is_dir():
        return []
    return sorted(
        p
        for p in chunk.iterdir()
        if p.is_file() and not p.is_symlink() and p.suffix.lower() in VIDEO_SUFFIXES
    )


def inspect_chunks(root: Path) -> dict:
    warnings: list[str] = []
    episodes = _episodes(root.resolve())
    chunks = subtitles = captions = clips = with_media = 0
    for episode in episodes:
        aggregate = _read_json(episode / "all_captions.json", warnings)
        for name in _chunk_names(episode, aggregate):
            chunk = episode / name
            media = _media_files(chunk)
            chunks += 1
            subtitles += (chunk / "subtitles.json").is_file()
            captions += (chunk / "structured_caption.txt").is_file() or bool(aggregate.get(name))
            clips += len(media)
            with_media += bool(media)
    return {
        "episodes": len(episodes),
        "chunks": chunks,
        "captioned_chunks": captions,
        "subtitle_files": subtitles,
        "video_clips": clips,
        "metadata_only_chunks": chunks - with_media,
        "warnings": warnings,
    }


def _caption(episode: Path, name: str, aggregate: dict, warnings: list[str]) -> tuple[str, Path]:
    source = episode / "all_captions.json"
    item = aggregate.get(name)
    if isinstance(item, dict):
        identifiers_match = (
            str(item.get("episode", episode.name)).strip() == episode.name.strip()
            and str(item.get("chunk", name)).strip() == name
        )
        if not identifiers_match:
            warnings.append(
                f"Conflicting episode or chunk identifier in {source} for {name}; trying caption file"
            )
        elif isinstance(item.get("caption"), str) and item["caption"].strip():
            return item["caption"].strip(), source
    elif item is not None:
        warnings.append(f"Ignored invalid caption entry in {source} for {name}")
    source = episode / name / "structured_caption.txt"
    if source.is_file():
        try:
            text = source.read_text(encoding="utf-8-sig")
            if text.startswith("Episode:"):
                header, separator, body = text.partition("\n\n")
                fields = dict(line.split(":", 1) for line in header.splitlines() if ":" in line)
                if (
                    fields.get("Episode", episode.name).strip() != episode.name.strip()
                    or fields.get("Chunk", name).strip() != name
                ):
                    warnings.append(f"Ignored caption with conflicting identifier at {source}")
                    return "", source
                text = body if separator else ""
            return text.strip(), source
        except (OSError, UnicodeError) as exc:
            warnings.append(f"Cannot read caption at {source}: {exc}")
    return "", source


def _dialogue(chunk: Path, low: float, high: float, warnings: list[str]) -> list[Dialogue]:
    source = chunk / "subtitles.json"
    metadata = _read_json(source, warnings)
    entries = metadata.get("subtitles_with_timestamps", [])
    if not isinstance(entries, list):
        warnings.append(f"Ignored invalid subtitle array at {source}")
        return []
    dialogue: list[Dialogue] = []
    seen: set[tuple[float, float, str]] = set()
    provenance = Provenance(source=str(source), method="imported_subtitle")
    for index, entry in enumerate(entries):
        try:
            if not isinstance(entry, dict):
                raise ValueError("expected an object")
            text = entry.get("text")
            if not isinstance(text, str) or not text.strip():
                raise ValueError("missing subtitle text")
            if isinstance(entry.get("start"), bool) or isinstance(entry.get("end"), bool):
                raise ValueError("timestamps must be numbers")
            line = Dialogue(
                start=entry["start"], end=entry["end"], text=text.strip(), provenance=provenance
            )
            if line.start >= high or line.end <= low:
                raise ValueError("subtitle does not overlap its original chunk interval")
            key = (line.start, line.end, line.text)
            if key not in seen:
                dialogue.append(line)
                seen.add(key)
        except (KeyError, ValueError, TypeError, ValidationError):
            warnings.append(f"Skipped invalid subtitle {index + 1} at {source}")
    return sorted(dialogue, key=lambda d: (d.start, d.end))


def _sections(caption: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in caption.splitlines():
        clean = line.strip().strip("#* ").rstrip(":").strip()
        if clean in HEADINGS:
            current = clean
            sections.setdefault(current, [])
        elif line.lstrip().startswith("#"):
            current = None
        elif current and line.strip():
            sections[current].append(line.strip())
    return sections


def _observations(caption: str, provenance: Provenance) -> list[Observation]:
    sections = _sections(caption)
    observations: list[Observation] = []
    seen: set[tuple[str, str, str | None]] = set()

    def add(kind: ObservationKind, value: str, evidence: str, subject: str | None = None):
        value = value.strip(" -*\t")
        key = (kind.value, value.casefold(), subject)
        if value and key not in seen:
            observations.append(
                Observation(
                    kind=kind,
                    value=value,
                    subject=subject,
                    evidence=evidence,
                    provenance=provenance,
                )
            )
            seen.add(key)

    for line in sections.get("CHARACTERS PRESENT", []):
        clean = line.lstrip("-* ").replace("**", "")
        name, separator, details = clean.partition(":")
        if not separator or not name.strip() or len(name.strip()) > 80:
            continue
        name = name.strip()
        add(ObservationKind.CHARACTER, name, line)
        for item in re.split(r"\s+-\s+|,\s*", details):
            if GARMENTS.search(item) and not re.search(
                r"\b(hair|expression)\b", item, re.IGNORECASE
            ):
                add(ObservationKind.CLOTHING, item, line, name)
    for heading, kind in [
        ("SCENE SETTING", ObservationKind.LOCATION),
        ("ACTIONS AND INTERACTIONS", ObservationKind.ACTION),
        ("OBJECTS AND PROPS", ObservationKind.OBJECT),
    ]:
        for line in sections.get(heading, []):
            if line.casefold().strip(".- ") not in {
                "none",
                "none observed",
                "unclear",
                "not visible",
            }:
                add(kind, line, line)
    return observations


def _probe_duration(
    path: Path, probe: str | None, warnings: list[str]
) -> tuple[bool, float | None]:
    if path.stat().st_size == 0:
        warnings.append(f"Ignored empty media file at {path}")
        return False, None
    if probe is None:
        return True, None
    try:
        result = subprocess.run(
            [
                probe,
                "-v",
                "error",
                "-show_entries",
                "format=duration:stream=codec_type",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=20,
            check=True,
        )
        data = json.loads(result.stdout)
        if not any(s.get("codec_type") == "video" for s in data.get("streams", [])):
            raise ValueError("no video stream")
        duration = float(data["format"]["duration"])
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("invalid duration")
        return True, duration
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        warnings.append(f"Could not validate media at {path}; playback unavailable")
        return False, None


def import_chunks(
    root: Path,
    collection_id: str = "friends",
    limit: int | None = None,
    ffprobe_path: str | None = None,
) -> ImportResult:
    if limit is not None and limit < 1:
        raise InvalidInput("Import limit must be at least 1")
    if not collection_id.strip():
        raise InvalidInput("Collection identifier must not be empty")
    result = ImportResult()
    episodes = _episodes(root.resolve())
    if not episodes:
        raise InvalidInput(
            "No episode folders or processed chunks were found in the import directory"
        )
    probe = shutil.which(ffprobe_path or os.environ.get("FFPROBE_PATH", "ffprobe"))
    unprobed_media = False
    for episode in episodes:
        aggregate = _read_json(episode / "all_captions.json", result.warnings)
        names = _chunk_names(episode, aggregate)
        video_id = stable_id(f"{collection_id}:{episode.name.strip()}")
        episode_scenes: list[Scene] = []
        for name in names:
            if limit is not None and len(result.scenes) + len(episode_scenes) >= limit:
                break
            chunk = episode / name
            low, high = (int(name[6:]) - 1) * 60.0, int(name[6:]) * 60.0
            caption, caption_source = _caption(episode, name, aggregate, result.warnings)
            dialogue = _dialogue(chunk, low, high, result.warnings)
            if not caption and not dialogue:
                result.warnings.append(
                    f"Skipped chunk without usable caption or timed subtitles: {chunk}"
                )
                continue
            provenance = Provenance(source=str(caption_source), method="imported_generated_caption")
            media = None
            media_files = _media_files(chunk)
            if len(media_files) > 1:
                result.warnings.append(
                    f"Multiple video files at {chunk}; using the first validated file in filename order"
                )
            for path in media_files:
                valid, duration = _probe_duration(path, probe, result.warnings)
                if valid:
                    media = Media(path=str(path.resolve()), duration=duration)
                    unprobed_media |= probe is None
                    break
            start: float | None = low
            end: float | None = high
            basis = "inferred_fixed_60_second_chunk"
            if name == names[-1]:
                if media and media.duration:
                    end = low + media.duration
                    basis = "inferred_chunk_offset_and_probed_media_duration"
                elif dialogue:
                    end = max(line.end for line in dialogue)
                    basis = "inferred_chunk_start_and_subtitle_evidence_end"
                else:
                    start, end, basis = None, None, "unknown_final_chunk_duration"
            episode_scenes.append(
                Scene(
                    scene_id=stable_id(f"{collection_id}:{episode.name.strip()}:{name}"),
                    video_id=video_id,
                    collection_id=collection_id,
                    episode_id=episode.name.strip(),
                    source_chunk=name,
                    start=start,
                    end=end,
                    timestamp_basis=basis,
                    description=caption,
                    dialogue=dialogue,
                    observations=_observations(caption, provenance),
                    provenance=([provenance] if caption else [])
                    + [Provenance(source=str(chunk), method=basis)],
                    media=media,
                )
            )
        if episode_scenes:
            result.videos.append(
                Video(
                    video_id=video_id,
                    collection_id=collection_id,
                    title=episode.name.strip(),
                    original_id=episode.name,
                    source_kind="import",
                )
            )
            result.scenes.extend(episode_scenes)
        if limit is not None and len(result.scenes) >= limit:
            break
    if unprobed_media:
        result.warnings.append(
            "FFprobe is unavailable; media files exist but their duration and stream content could not be validated"
        )
    missing = sum(scene.media is None for scene in result.scenes)
    if missing:
        result.warnings.append(
            f"{missing} imported scenes have no validated video file; results are metadata-only"
        )
    return result
