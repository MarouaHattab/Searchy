import hashlib
import json
import math
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from searchy.core import InvalidInput
from searchy.domain import (
    Dialogue,
    DialogueReference,
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
    aggregate_source = episode / "all_captions.json"
    file_source = episode / name / "structured_caption.txt"
    item = aggregate.get(name)
    aggregate_caption = ""
    if isinstance(item, dict):
        identifiers_match = (
            str(item.get("episode", episode.name)).strip() == episode.name.strip()
            and str(item.get("chunk", name)).strip() == name
        )
        if not identifiers_match:
            warnings.append(
                f"Conflicting episode or chunk identifier in {aggregate_source} for {name}; "
                "trying caption file"
            )
        elif isinstance(item.get("caption"), str) and item["caption"].strip():
            aggregate_caption = item["caption"].strip()
    elif item is not None:
        warnings.append(f"Ignored invalid caption entry in {aggregate_source} for {name}")
    if file_source.is_file():
        try:
            text = file_source.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as exc:
            warnings.append(f"Cannot read caption at {file_source}: {exc}")
            text = ""
        if text.startswith("Episode:"):
            header, separator, body = text.partition("\n\n")
            fields = dict(line.split(":", 1) for line in header.splitlines() if ":" in line)
            if (
                fields.get("Episode", episode.name).strip() != episode.name.strip()
                or fields.get("Chunk", name).strip() != name
            ):
                warnings.append(f"Ignored caption with conflicting identifier at {file_source}")
                return "", file_source
            text = body if separator else ""
        text = text.strip()
        if text:
            if aggregate_caption and aggregate_caption != text:
                warnings.append(
                    f"{episode.name}/{name}: all_captions.json differs from structured_caption.txt; "
                    "using the chunk file"
                )
            return text, file_source
    if aggregate_caption:
        return aggregate_caption, aggregate_source
    return "", file_source


def _resolve_speaker(label: str, character_names: list[str]) -> str | None:
    normalized = " ".join(label.casefold().split())
    if normalized in {"both", "everyone", "group", "offscreen", "unknown"}:
        return None
    exact = [name for name in character_names if " ".join(name.casefold().split()) == normalized]
    aliases = [
        name
        for name in character_names
        if name.split()[0].casefold() == normalized
        or (len(name.split()) > 1 and name.split()[-1].casefold() == normalized)
    ]
    candidates = exact or aliases
    if len(candidates) == 1:
        return candidates[0]
    return None


def _labeled_segments(text: str, character_names: list[str]) -> list[tuple[str | None, str]]:
    marker = re.compile(r"(?<!\w)([A-Z][A-Z0-9 .'-]{0,39}):\s*")
    matches = list(marker.finditer(text))
    if not matches:
        return [(None, text.strip())]
    leading = text[: matches[0].start()].strip(" -\t")
    labels = [match.group(1).strip() for match in matches]
    speakers = [_resolve_speaker(label, character_names) for label in labels]
    if leading or not all(speakers):
        # A group/unknown label, or mixed dialogue without a clear boundary, is
        # preserved as unattributed transcript evidence.
        if not leading and len(matches) == 1 and labels[0].casefold() in {
            "both",
            "everyone",
            "group",
            "offscreen",
            "unknown",
        }:
            return [(None, text[matches[0].end() :].strip())]
        return [(None, text.strip())]
    segments = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.end() : end].strip(" -\t")
        if body:
            segments.append((speakers[index], body))
    return segments or [(None, text.strip())]


def _dialogue_references(
    text: str, speaker: str | None, character_names: list[str], collection_id: str | None
) -> list[DialogueReference]:
    references = []
    lowered = text.casefold()
    for name in character_names:
        aliases = {name.casefold()}
        first = name.split()[0]
        if sum(other.split()[0].casefold() == first.casefold() for other in character_names) == 1:
            aliases.add(first.casefold())
        mentioned = any(
            re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", lowered) for alias in aliases
        )
        if mentioned:
            references.append(
                DialogueReference(
                    name=name,
                    character_id=stable_id(
                        f"character:{collection_id or 'default'}:{' '.join(name.casefold().split())}"
                    ),
                    relation="mentioned",
                    confidence=1.0,
                    evidence=name,
                )
            )
        job_terms = r"(?:job|work|career|occupation|profession|role|position)"
        about = any(
            re.search(
                rf"(?<!\w){re.escape(alias)}(?:['’]s)?\s+(?:new\s+|current\s+|former\s+)?{job_terms}(?!\w)",
                lowered,
            )
            or re.search(
                rf"(?<!\w){re.escape(alias)}\s+(?:is|was|works?|worked|became|has|does)\b",
                lowered,
            )
            for alias in aliases
        )
        if about:
            references.append(
                DialogueReference(
                    name=name,
                    character_id=stable_id(
                        f"character:{collection_id or 'default'}:{' '.join(name.casefold().split())}"
                    ),
                    relation="subject",
                    confidence=1.0,
                    evidence=name,
                )
            )
    if speaker and re.search(
        r"\b(?:my\s+(?:job|work|career|occupation|profession|role)|"
        r"i\s+(?:work|worked)\s+(?:as|in)\s+\w+|"
        r"i\s+(?:work|worked|am|was|became)\s+(?:as\s+)?(?:a|an|the)\s+\w+|"
        r"(?:make|makes|made|promote\w*)\s+me\s+(?:(?:a|an|the)\s+)?\w+)",
        lowered,
    ) and not any(
        ref.name.casefold() == speaker.casefold() and ref.relation == "subject"
        for ref in references
    ):
        references.append(
            DialogueReference(
                name=speaker,
                character_id=stable_id(
                    f"character:{collection_id or 'default'}:{' '.join(speaker.casefold().split())}"
                ),
                relation="subject",
                confidence=1.0,
                evidence="explicit first-person statement by attributed speaker",
            )
        )
    return references


def _dialogue(
    chunk: Path,
    low: float,
    high: float,
    warnings: list[str],
    character_names: list[str] | None = None,
    collection_id: str | None = None,
) -> list[Dialogue]:
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
            source_start, source_end = float(entry["start"]), float(entry["end"])
            if source_start >= high or source_end <= low:
                raise ValueError("subtitle does not overlap its original chunk interval")
            clipped_start, clipped_end = max(source_start, low), min(source_end, high)
            for speaker, body in _labeled_segments(text.strip(), character_names or []):
                refs = _dialogue_references(
                    body, speaker, character_names or [], collection_id
                )
                line = Dialogue(
                    start=clipped_start,
                    end=clipped_end,
                    source_start=source_start,
                    source_end=source_end,
                    text=body,
                    speaker=speaker,
                    speaker_id=(
                        stable_id(
                            f"character:{collection_id or 'default'}:{' '.join(speaker.casefold().split())}"
                        )
                        if speaker
                        else None
                    ),
                    speaker_confidence=1.0 if speaker else None,
                    references=refs,
                    provenance=provenance,
                )
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


def _visual_description(caption: str) -> str:
    sections = _sections(caption)
    allowed = {
        "SCENE SETTING",
        "CHARACTERS PRESENT",
        "ACTIONS AND INTERACTIONS",
        "OBJECTS AND PROPS",
        "TEMPORAL NOTES",
    }
    return "\n".join(
        f"{heading}:\n" + "\n".join(lines)
        for heading, lines in sections.items()
        if heading in allowed and lines
    )


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


def _clip_timing(
    path: Path, duration: float | None, warnings: list[str]
) -> tuple[float, Provenance | None]:
    source = path.parent / "media_timing.json"
    if not source.is_file():
        return 0.0, None
    metadata = _read_json(source, warnings)
    try:
        if (
            metadata.get("episode") != path.parent.parent.name
            or metadata.get("chunk") != path.parent.name
            or metadata.get("filename") != path.name
        ):
            raise ValueError("episode, chunk, or filename does not match")
        offset = metadata.get("start_offset")
        if (
            isinstance(offset, bool)
            or not isinstance(offset, (int, float))
            or not math.isfinite(offset)
            or offset < 0
            or (duration is not None and offset >= duration)
        ):
            raise ValueError("invalid media start offset")
        with path.open("rb") as stream:
            actual_hash = hashlib.file_digest(stream, "sha256").hexdigest()
        if metadata.get("sha256") != actual_hash:
            raise ValueError("media SHA-256 does not match")
        evidence = metadata.get("evidence")
        if (
            isinstance(evidence, dict)
            and evidence.get("method") == "shared_encoded_video_packet_sha256"
        ):
            shared = evidence.get("shared_packets")
            consensus = evidence.get("consensus_packets")
            spread = evidence.get("spread")
            audio = evidence.get("agreeing_audio_packets")
            numbers = (shared, consensus, audio, spread)
            if any(isinstance(value, bool) for value in numbers) or not (
                isinstance(shared, int)
                and isinstance(consensus, int)
                and isinstance(audio, int)
                and isinstance(spread, int | float)
                and shared >= 3
                and consensus / shared >= 0.8
                and audio >= 3
                and math.isfinite(spread)
                and spread < 0.002
            ):
                raise ValueError("packet-overlap evidence is below the acceptance threshold")
        return float(offset), Provenance(
            source=str(source), method="inferred_clip_offset_from_encoded_packet_overlap"
        )
    except (OSError, ValueError) as exc:
        warnings.append(f"Ignored invalid clip timing at {source}: {exc}")
        return 0.0, None


def import_chunks(
    root: Path,
    collection_id: str = "friends",
    limit: int | None = None,
    ffprobe_path: str | None = None,
    episode_media_dir: Path | None = None,
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
        captions = {
            name: _caption(episode, name, aggregate, result.warnings) for name in names
        }
        roster_provenance = Provenance(source=str(episode), method="caption_character_roster")
        character_names = sorted(
            {
                observation.value
                for caption, _ in captions.values()
                for observation in _observations(caption, roster_provenance)
                if observation.kind == ObservationKind.CHARACTER
            }
        )
        video_id = stable_id(f"{collection_id}:{episode.name.strip()}")
        full_media = None
        if episode_media_dir is not None:
            normalized = " ".join(episode.name.casefold().split())
            matches = [
                path
                for path in _media_files(episode_media_dir)
                if " ".join(path.stem.casefold().split()) == normalized
            ]
            if len(matches) > 1:
                raise InvalidInput(f"Ambiguous full-episode media for {episode.name}")
            if matches:
                if probe is None:
                    result.warnings.append(
                        f"FFprobe is required to attach full-episode media for {episode.name}"
                    )
                else:
                    valid, duration = _probe_duration(matches[0], probe, result.warnings)
                    if valid and duration is not None:
                        full_media = Media(path=str(matches[0].resolve()), duration=duration)
        episode_scenes: list[Scene] = []
        for name in names:
            if limit is not None and len(result.scenes) + len(episode_scenes) >= limit:
                break
            chunk = episode / name
            low, high = (int(name[6:]) - 1) * 60.0, int(name[6:]) * 60.0
            caption, caption_source = captions[name]
            dialogue = _dialogue(
                chunk,
                low,
                high,
                result.warnings,
                character_names=character_names,
                collection_id=collection_id,
            )
            if not caption and not dialogue:
                result.warnings.append(
                    f"Skipped chunk without usable caption or timed subtitles: {chunk}"
                )
                continue
            provenance = Provenance(source=str(caption_source), method="imported_generated_caption")
            media = None
            timing_provenance = None
            media_files = _media_files(chunk)
            if len(media_files) > 1:
                result.warnings.append(
                    f"Multiple video files at {chunk}; using the first validated file in filename order"
                )
            for path in media_files:
                valid, duration = _probe_duration(path, probe, result.warnings)
                if valid:
                    offset, timing_provenance = _clip_timing(path, duration, result.warnings)
                    media = Media(
                        path=str(path.resolve()), duration=duration, start_offset=offset
                    )
                    unprobed_media |= probe is None
                    break
            start: float | None = low
            end: float | None = high
            basis = "inferred_fixed_60_second_chunk"
            if timing_provenance and media is not None:
                # A verified start_offset is the true position of this clip in
                # the episode. Using the nominal 60s grid here would put every
                # citation, crop and thumbnail off by the keyframe drift, which
                # the shipped dataset measures at up to ~3 seconds.
                start = media.start_offset
                end = media.start_offset + (
                    (low + media.duration - media.start_offset) - low
                    if media.duration
                    else (high - low)
                )
                basis = "verified_packet_aligned_chunk_offset"
            if name == names[-1]:
                if media and media.duration:
                    end = low + media.duration - media.start_offset
                    basis = "inferred_chunk_offset_and_probed_media_duration"
                elif dialogue:
                    end = max(line.end for line in dialogue)
                    basis = "inferred_chunk_start_and_subtitle_evidence_end"
                else:
                    start, end, basis = None, None, "unknown_final_chunk_duration"
            chunk_provenance = Provenance(source=str(chunk), method=basis)
            media_provenance = []
            if timing_provenance:
                media_provenance.append(timing_provenance)
            if media is None and full_media is not None:
                if low < full_media.duration:
                    media = full_media.model_copy(update={"start_offset": low})
                    start, end = low, min(high, full_media.duration)
                    basis = "inferred_nominal_chunk_offset_bounded_by_episode_duration"
                    media_provenance.append(
                        Provenance(
                            source=full_media.path,
                            method="matched_full_episode_using_nominal_60_second_chunk_offset",
                        )
                    )
                else:
                    result.warnings.append(
                        f"{episode.name}/{name} starts beyond the full-episode duration; "
                        "retained original clip or metadata-only availability"
                    )
            if start is not None and end is not None:
                bounded_dialogue = []
                for line in dialogue:
                    clipped_start = max(line.start, start)
                    clipped_end = min(line.end, end)
                    if clipped_end > clipped_start:
                        line.start = clipped_start
                        line.end = clipped_end
                        bounded_dialogue.append(line)
                dialogue = bounded_dialogue
            observations = _observations(caption, provenance)
            if start is not None and end is not None:
                for observation in observations:
                    observation.start, observation.end = start, end
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
                    description=_visual_description(caption),
                    visual_description=_visual_description(caption),
                    scene_summary="",
                    dialogue=dialogue,
                    observations=observations,
                    provenance=([provenance] if caption else [])
                    + [chunk_provenance]
                    + media_provenance,
                    media=media,
                )
            )
        if episode_scenes:
            attached_episode = (
                full_media
                if full_media is not None
                and any(
                    scene.media is not None and scene.media.path == full_media.path
                    for scene in episode_scenes
                )
                else None
            )
            result.videos.append(
                Video(
                    video_id=video_id,
                    collection_id=collection_id,
                    title=episode.name.strip(),
                    original_id=episode.name,
                    source_kind="import",
                    duration=attached_episode.duration if attached_episode else None,
                    media_path=attached_episode.path if attached_episode else None,
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
