import argparse
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from searchy.core.config import Settings
from searchy.core.errors import InvalidInput, SearchyError

SECTIONS = (
    "SCENE SETTING",
    "CHARACTERS PRESENT",
    "ACTIONS AND INTERACTIONS",
    "OBJECTS AND PROPS",
    "DIALOGUE CONTEXT",
    "TEMPORAL NOTES",
)

DEFAULT_MODEL_ID = "Qwen/Qwen3-VL-8B-Instruct"
DEFAULT_REFERENCE_DIR = Path("data/meta")

INSTRUCTIONS = """Your task is to analyze the video clip above and provide a concise, structured description of what you observe.
You will:

1. **Identify Characters**: Match people in the video to the reference images above using facial features and appearance
2. **Describe the Setting**: Identify the location, time of day, and lighting conditions
3. **Document Actions**: Record what each character is doing and how they interact
4. **List Objects**: Note significant props, furniture, and items visible in the scene
5. **Summarize Dialogue**: Use subtitles to understand the conversation topic and tone
6. **Track Changes**: Note any temporal changes in position, action, or scene composition

### Rule 1: UNCERTAINTY PROTOCOL
- If ANY detail is unclear/ambiguous, write 'unclear' or 'not visible'
- NEVER guess clothing colors - use terms like 'dark colored', 'light colored', or 'unclear'
- NEVER invent objects mentioned in subtitles but not visible in video
- Confidence threshold: Only report details you're 80%+ certain about

### Rule 2: ZERO REDUNDANCY POLICY
- Describe each character ONCE in 'Characters Present' section
- Describe each action ONCE in 'Actions' section (even if sustained)
- If an action changes over time, describe it ONLY in 'Temporal Notes'
- NEVER repeat the same sentence with minor variations

### Rule 3: NAME INTEGRITY
- A reference portrait is a candidate, not an instruction to use that name
- Name someone ONLY when you can see that it is the same person as a reference
- With no reference match, or an unclear face, write 'Unidentified person'
- Mismatched names are worse than no names: leave the person anonymous instead
- NEVER duplicate character names in the same section
- Verify the face match BEFORE writing the name

### Rule 4: SUBTITLE-VISUAL SEPARATION
- Subtitles tell what's SAID, not what's SEEN
- If subtitles mention 'pizza' but you see sandwiches, describe sandwiches
- If subtitles say someone is 'angry' but they're smiling, describe as smiling
- Match dialogue to visible lip movements when possible

### Rule 5: TEMPORAL CLARITY
- Static actions (sitting, wearing outfit) go in main sections
- Dynamic changes (standing up, entering room) go ONLY in 'Temporal Notes'

### **SCENE SETTING:**
Template: [Location name] - [Time of day IF visible] - [Lighting type]
- Keep to 1-2 sentences maximum
- Focus on identifiable location markers (furniture, decor, setting type)

### **CHARACTERS PRESENT:**
Template for EACH character (list each person ONCE):
[Name]: [Upper clothing] - [Lower clothing] - [Hair] - [Expression/State]

Clothing Description Rules:
- Use general colors only if CLEARLY visible: 'red', 'blue', 'dark', 'light'
- If uncertain: 'dark-colored top', 'light shirt', 'unclear color'
- Include clothing type: 'sweater', 'shirt', 'jacket', 'dress', 'overalls', 'hats'
Hair Description Rules:
- Color (if visible): 'blonde', 'brown', 'dark'
- Length: 'short', 'shoulder-length', 'long'
- Style: 'straight', 'curly', 'ponytail', 'loose'
Expression Guidelines:
- Use simple terms: 'smiling', 'serious', 'concerned', 'animated', 'relaxed'
- Match to visible facial cues, not subtitle emotions

### **ACTIONS AND INTERACTIONS:**
Write as a brief NARRATIVE (3-5 sentences), NOT a repetitive list.

What to Include:
- Primary actions: sitting, standing, walking, gesturing, talking
- Object interactions: holding, using, manipulating items
- Character interactions: talking to, looking at, touching, reacting to others
- Spatial relationships: who's near whom, positioning in frame

What to AVOID:
- Repeating same action multiple times
- Over-describing sustained states: If someone sits throughout, mention once
- Listing every micro-gesture: Focus on significant actions only

### **OBJECTS AND PROPS:**
List format: [Object type]: [Color/description IF clear] ([location/context])

Guidelines:
- List 3-8 items maximum (most prominent/relevant)
- Skip background clutter unless significant
- Use 'unclear' for ambiguous objects
- Don't invent objects from subtitles

### **DIALOGUE CONTEXT:**
Based on subtitles + visual cues, describe in 2-4 sentences:

Include:
- Topic: What are they discussing? (use subtitles)
- Participants: Who's speaking to whom? (use visuals)
- Tone: happy, serious, joking, tense, casual (match facial expressions)
- Reactions: Notable responses from listeners

### **TEMPORAL NOTES:**
ONLY include if actions/positions CHANGE during the clip.

Format: [Character] [specific change]

What qualifies as a change:
- Movement: entering, exiting, standing up, sitting down
- Object interaction shifts: picks up, sets down, passes
- Major expression changes: calm -> excited, serious -> laughing
- Position changes: moves to different location in frame

What NOT to include:
- Sustained actions (already in main sections)
- Minor gestures (hand movements during conversation)

Before submitting your description, verify:

Character Names:
  - Each name appears ONCE in 'Characters Present'
  - All names match reference images exactly

Color Accuracy:
  - Replaced any uncertain colors with 'dark', 'light', or 'unclear'

Redundancy Elimination:
  - No repeated sentences or near-identical descriptions

Hallucination Prevention:
  - Removed any objects not actually visible
  - Verified actions match what's shown, not just subtitles

Temporal Accuracy:
  - Static info in main sections, changes ONLY in Temporal Notes

Format Compliance:
  - All six section headers included, in the order above
  - Concise writing (quality > quantity)
"""


@dataclass(frozen=True)
class Reference:
    name: str
    path: Path


@dataclass
class CaptionResult:
    chunk: str
    caption: str | None = None
    error: str | None = None
    subtitles: str | None = None


@dataclass
class EpisodeCaptions:
    episode: str
    folder: Path
    captions: list[CaptionResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def normalize_whitespace(text: str) -> str:
    return " ".join(text.split())


def chunk_folders(episode_path: Path) -> list[Path]:
    folders = [
        path
        for path in episode_path.iterdir()
        if path.is_dir() and not path.is_symlink() and re.fullmatch(r"chunk_\d+", path.name)
    ]
    return sorted(folders, key=lambda path: int(path.name.split("_")[1]))


def load_references(directory: Path | None, limit: int = 6) -> list[Reference]:
    if directory is None or not directory.is_dir():
        return []
    references = []
    for path in sorted(directory.glob("*.png"))[:limit]:
        if path.is_file() and not path.is_symlink() and path.stat().st_size:
            references.append(Reference(name=path.stem, path=path))
    return references


def collection_references(
    settings: Settings, collection_id: str | None, limit: int = 6
) -> list[Reference]:
    """Portraits registered for this collection only.

    A global folder tells the model that every video contains those people, which
    makes it label a stranger with a known name rather than describe who is
    actually there. References are therefore scoped to the collection being
    captioned, and an empty result means people stay unidentified.
    """
    if not collection_id:
        return []
    try:
        from searchy.storage.characters import CharacterStore

        store = CharacterStore(settings.database_path)
        references: list[Reference] = []
        for character in store.list(collection_id):
            if character.get("status") != "ready":
                continue
            for entry in character.get("references") or []:
                path = Path(entry.get("path") or "")
                if (
                    entry.get("validation") in {"face_ready", "image_validated"}
                    and path.is_file()
                    and not path.is_symlink()
                    and path.stat().st_size
                ):
                    references.append(Reference(name=character["name"], path=path))
                    break
            if len(references) >= limit:
                break
        return references
    except Exception:
        return []


def chunk_subtitles(chunk_path: Path) -> str:
    source = chunk_path / "subtitles.json"
    if not source.is_file():
        return ""
    try:
        data = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return ""
    without_time = data.get("subtitles_without_timestamps") if isinstance(data, dict) else None
    if not isinstance(without_time, list):
        return ""
    return normalize_whitespace("\n".join(str(item) for item in without_time))


def chunk_video(chunk_path: Path) -> Path | None:
    for suffix in (".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v"):
        for path in sorted(chunk_path.glob(f"*{suffix}")):
            if path.is_file() and path.stat().st_size:
                return path
    return None


def build_messages(
    video: Path,
    subtitles_text: str,
    references: list[Reference],
    episode_name: str,
    video_options: dict | None = None,
) -> list[dict]:
    content: list[dict] = []
    if references:
        content.append(
            {
                "type": "text",
                "text": (
                    "## CHARACTER REFERENCE GUIDE\n"
                    "These portraits show people who may appear in the clip. Compare faces by "
                    "facial features and overall appearance.\n"
                    "Use one of these names ONLY when the person in the footage is clearly the "
                    "same individual as the reference. If nobody in the footage matches, or the "
                    "face is unclear, write 'Unidentified person' with a null subject instead. "
                    "Never assign a name to make the description fit."
                ),
            }
        )
        for index, reference in enumerate(references, 1):
            content.append({"type": "image", "image": str(reference.path)})
            content.append(
                {"type": "text", "text": f"Reference {index}: {reference.name} (memorize face)"}
            )
    content.append({"type": "text", "text": f"\n## VIDEO TO ANALYZE\nEpisode: {episode_name}"})
    content.append(
        {"type": "video", "video": str(video), **(video_options or {"fps": 1.0})}
    )
    content.append(
        {
            "type": "text",
            "text": (
                f'## SUBTITLES (Context Only)\n"{subtitles_text}"\n\n' + INSTRUCTIONS
            ),
        }
    )
    return [{"role": "user", "content": content}]


def validate_caption(text: str) -> str:
    caption = text.strip()
    if not caption:
        raise SearchyError("The caption model returned an empty description")
    missing = [
        section
        for section in SECTIONS
        if not re.search(rf"\**{re.escape(section)}\**:?", caption, re.IGNORECASE)
    ]
    if missing:
        raise SearchyError(
            "The caption model omitted required sections: " + ", ".join(missing)
        )
    return caption


def caption_file_text(episode_name: str, chunk_name: str, subtitles_text: str, caption: str) -> str:
    return (
        f"Episode: {episode_name}\n"
        f"Chunk: {chunk_name}\n"
        f"Subtitles: {subtitles_text}\n\n"
        f"{caption}"
    )


def write_caption(chunk_path: Path, text: str) -> Path:
    target = chunk_path / "structured_caption.txt"
    pending = chunk_path / "structured_caption.pending.txt"
    pending.write_text(text, encoding="utf-8")
    pending.replace(target)
    return target


def read_episode_aggregate(folder: Path) -> dict[str, dict]:
    source = folder / "all_captions.json"
    if not source.is_file():
        return {}
    try:
        data = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {name: entry for name, entry in data.items() if isinstance(entry, dict)}


def write_episode_aggregate(folder: Path, entry: dict[str, dict]) -> Path:
    target = folder / "all_captions.json"
    pending = folder / "all_captions.pending.json"
    merged = {**read_episode_aggregate(folder), **entry}
    pending.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")
    pending.replace(target)
    return target


class Captioner:

    def __init__(
        self,
        settings: Settings,
        model_id: str = DEFAULT_MODEL_ID,
        reference_dir: Path | None = DEFAULT_REFERENCE_DIR,
        temperature: float = 0.2,
        max_tokens: int = 10000,
        frames: int = 3,
    ):
        self.settings = settings
        self.model_id = model_id
        self.references = load_references(reference_dir)
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.frames = max(1, frames)
        self.server_context = 8192
        self._processor = None
        self._model = None
        os.environ.setdefault("VLLM_WORKER_MULTIPROC_METHOD", "spawn")

    def _load(self):
        if self._model is not None:
            return self._processor, self._model
        try:
            from transformers import AutoProcessor
            from vllm import LLM
        except ImportError:
            raise SearchyError(
                "Local captioning requires: uv sync --extra preprocess"
            ) from None
        try:
            self._processor = AutoProcessor.from_pretrained(self.model_id)
            self._model = LLM(
                model=self.model_id,
                tensor_parallel_size=1,
                max_model_len=10000,
                enforce_eager=True,
                enable_prefix_caching=True,
                gpu_memory_utilization=0.95,
                seed=0,
            )
        except Exception:
            raise SearchyError(
                f"Cannot load caption model '{self.model_id}'. Check GPU memory and model access."
            ) from None
        return self._processor, self._model

    def _server_stills(self, video: Path, cache: Path) -> list[Path]:
        from searchy.processing.video import VideoProcessor

        processor = VideoProcessor(self.settings)
        duration = processor.probe(video).duration
        cache.mkdir(parents=True, exist_ok=True)
        sampled = []
        for index in range(max(1, self.frames)):
            timestamp = duration * (index + 1) / (max(1, self.frames) + 1)
            target = cache / f"srv-{timestamp:.6f}.jpg"
            if not target.is_file() or target.stat().st_size == 0:
                pending = target.with_suffix(".pending.jpg")
                processor._run(
                    [
                        self.settings.ffmpeg_path,
                        "-nostdin",
                        "-v",
                        "error",
                        "-ss",
                        f"{timestamp:.6f}",
                        "-i",
                        str(video),
                        "-frames:v",
                        "1",
                        "-vf",
                        "scale=448:448:force_original_aspect_ratio=decrease",
                        "-q:v",
                        "3",
                        "-y",
                        str(pending),
                    ],
                    "FFmpeg frame extraction",
                )
                if not pending.is_file() or pending.stat().st_size == 0:
                    raise SearchyError("FFmpeg did not produce a frame for captioning")
                pending.replace(target)
            sampled.append(target)
        return sampled

    def _caption_via_ollama(self, prompt: str, images: list[Path], base: str) -> str:
        import base64

        import httpx

        settings = self.settings
        try:
            encoded = [base64.b64encode(path.read_bytes()).decode("ascii") for path in images]
        except OSError:
            raise SearchyError("A captioning still could not be read") from None
        body = {
            "model": self.model_id or settings.caption_model_id,
            "messages": [{"role": "user", "content": prompt, "images": encoded}],
            "stream": False,
            "think": False,
            "options": {
                "num_ctx": self.server_context,
                "temperature": self.temperature,
                "num_predict": max(self.max_tokens, 4000),
            },
        }
        try:
            with httpx.Client(timeout=max(settings.provider_timeout_seconds * 8, 900)) as client:
                response = client.post(f"{base}/api/chat", json=body)
        except httpx.RequestError:
            raise SearchyError(f"Local caption server at {base} is unreachable") from None
        if not response.is_success:
            raise SearchyError(f"Local caption server returned HTTP {response.status_code}")
        try:
            message = json.loads(response.content.decode("utf-8", "replace"))["message"]
        except (ValueError, KeyError):
            raise SearchyError("Local caption server returned an unusable response") from None
        text = message.get("content") or ""
        if not text.strip() and message.get("thinking"):
            text = message["thinking"]
        if not text.strip():
            raise SearchyError("Local caption server returned an empty description")
        return text

    def _caption_via_server(self, prompt: str, images: list[Path]) -> str:
        import base64
        import mimetypes

        import httpx

        settings = self.settings
        base = settings.vllm_base_url.rstrip("/")
        if base.endswith("/v1") and "11434" in base:
            return self._caption_via_ollama(prompt, images, base[: -len("/v1")])
        content: list[dict] = [{"type": "text", "text": prompt}]
        try:
            for index, path in enumerate(images):
                mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
                encoded = base64.b64encode(path.read_bytes()).decode("ascii")
                content.append(
                    {"type": "text", "text": f"Evidence still {index + 1} of {len(images)}"}
                )
                content.append(
                    {"type": "image_url", "image_url": f"data:{mime};base64,{encoded}"}
                )
        except OSError:
            raise SearchyError("A captioning still could not be read") from None

        body = {
            "messages": [{"role": "user", "content": content}],
            "temperature": self.temperature,
            "max_tokens": max(self.max_tokens, 4000),
            "think": False,
            "num_ctx": self.server_context,
        }
        if self.model_id:
            body["model"] = self.model_id
        try:
            with httpx.Client(timeout=settings.provider_timeout_seconds) as client:
                response = client.post(
                    f"{settings.vllm_base_url.rstrip('/')}/chat/completions", json=body
                )
        except httpx.RequestError:
            raise SearchyError(
                f"Local caption server at {settings.vllm_base_url} is unreachable"
            ) from None
        if not response.is_success:
            raise SearchyError(
                f"Local caption server returned HTTP {response.status_code}"
            )
        try:
            message = json.loads(response.content.decode("utf-8", "replace"))["choices"][0][
                "message"
            ]
        except (ValueError, KeyError, IndexError):
            raise SearchyError("Local caption server returned an unusable response") from None
        text = message.get("content") or ""
        if not text.strip() and message.get("reasoning"):
            text = message["reasoning"]
        if not text.strip():
            raise SearchyError("Local caption server returned an empty description")
        return text

    def caption(self, chunk_path: Path, episode_name: str) -> CaptionResult:
        video = chunk_video(chunk_path)
        if video is None:
            raise InvalidInput(f"No video file in {chunk_path.name}")
        subtitles_text = chunk_subtitles(chunk_path)

        if self.settings.vllm_base_url:
            cache = (
                self.settings.data_dir / "processing" / "captions" / chunk_path.name
            ).resolve()
            stills = self._server_stills(video, cache)
            messages = build_messages(video, subtitles_text, self.references, episode_name)
            prompt = "\n".join(
                part["text"] for part in messages[0]["content"] if part.get("type") == "text"
            )
            generated = self._caption_via_server(prompt, stills)
            return CaptionResult(
                chunk=chunk_path.name, caption=generated, subtitles=subtitles_text
            )

        processor, model = self._load()
        try:
            from qwen_vl_utils import process_vision_info
            from vllm import SamplingParams
        except ImportError:
            raise SearchyError(
                "Local captioning requires: uv sync --extra preprocess"
            ) from None

        messages = build_messages(
            video,
            subtitles_text,
            self.references,
            episode_name,
            {"fps": 1.0, "resized_height": 448, "resized_width": 448},
        )
        text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        image_inputs, video_inputs, video_kwargs = process_vision_info(
            messages,
            image_patch_size=processor.image_processor.patch_size,
            return_video_kwargs=True,
            return_video_metadata=True,
        )
        multi_modal_data = {}
        if image_inputs is not None:
            multi_modal_data["image"] = image_inputs
        if video_inputs is not None:
            multi_modal_data["video"] = video_inputs
        inputs = [
            {
                "prompt": text,
                "multi_modal_data": multi_modal_data,
                "mm_processor_kwargs": video_kwargs,
            }
        ]
        try:
            outputs = model.generate(
                inputs,
                sampling_params=SamplingParams(
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    top_p=0.95,
                    top_k=50,
                ),
                use_tqdm=False,
            )
            generated = outputs[0].outputs[0].text
        except Exception:
            raise SearchyError(f"Caption generation failed for {chunk_path.name}") from None
        return CaptionResult(
            chunk=chunk_path.name,
            caption=generated,
            subtitles=subtitles_text,
        )


class ApiCaptioner:

    def __init__(
        self,
        settings: Settings,
        model_id: str | None = None,
        reference_dir: Path | None = DEFAULT_REFERENCE_DIR,
        frames: int = 3,
    ):
        from searchy.models.vision import get_vision_provider

        self.settings = settings
        self.references = load_references(reference_dir)
        self.frames = max(1, frames)
        self.provider = get_vision_provider(
            settings,
            references=None,
            provider=settings.caption_provider,
            model_id=model_id or settings.caption_api_model_id or None,
        )

    def _sample_frames(self, video: Path, cache: Path) -> list[Path]:
        from searchy.processing.video import VideoProcessor

        processor = VideoProcessor(self.settings)
        duration = processor.probe(video).duration
        cache.mkdir(parents=True, exist_ok=True)
        sampled = []
        for index in range(self.frames):
            timestamp = duration * (index + 1) / (self.frames + 1)
            target = cache / f"frame-{timestamp:.6f}.jpg"
            if not target.is_file() or target.stat().st_size == 0:
                pending = target.with_suffix(".pending.jpg")
                processor._run(
                    [
                        self.settings.ffmpeg_path,
                        "-nostdin",
                        "-v",
                        "error",
                        "-ss",
                        f"{timestamp:.6f}",
                        "-i",
                        str(video),
                        "-frames:v",
                        "1",
                        "-vf",
                        "scale=448:448:force_original_aspect_ratio=decrease",
                        "-q:v",
                        "3",
                        "-y",
                        str(pending),
                    ],
                    "FFmpeg frame extraction",
                )
                if not pending.is_file() or pending.stat().st_size == 0:
                    raise SearchyError("FFmpeg did not produce a frame for captioning")
                pending.replace(target)
            sampled.append(target)
        return sampled

    def caption(self, chunk_path: Path, episode_name: str) -> CaptionResult:
        video = chunk_video(chunk_path)
        if video is None:
            raise InvalidInput(f"No video file in {chunk_path.name}")
        subtitles_text = chunk_subtitles(chunk_path)
        cache = (self.settings.data_dir / "processing" / "captions" / chunk_path.name).resolve()
        frames = self._sample_frames(video, cache)
        ids = {"fps": 1.0, "resized_height": 448, "resized_width": 448}
        messages = build_messages(
            video, subtitles_text, self.references, episode_name, ids
        )
        content = messages[0]["content"]
        rebuilt: list[dict] = []
        for part in content:
            if part.get("type") == "video":
                for index, frame in enumerate(frames):
                    rebuilt.append({"type": "image", "image": str(frame)})
                    rebuilt.append(
                        {"type": "text", "text": f"Evidence still {index + 1} of {len(frames)}"}
                    )
            else:
                rebuilt.append(part)
        prompt = "\n".join(
            part["text"] for part in rebuilt if part.get("type") == "text"
        )
        try:
            generated = self.provider.describe(prompt) if frames else ""
        except SearchyError:
            raise
        except Exception:
            raise SearchyError(f"Caption generation failed for {chunk_path.name}") from None
        if not generated.strip():
            raise SearchyError("The caption model returned an empty description")
        return CaptionResult(
            chunk=chunk_path.name,
            caption=generated,
            subtitles=subtitles_text,
        )


def build_captioner(
    settings: Settings,
    backend: str,
    model_id: str | None = None,
    reference_dir: Path | None = DEFAULT_REFERENCE_DIR,
):
    if backend == "local":
        return Captioner(settings, model_id or DEFAULT_MODEL_ID, reference_dir)
    if backend == "api":
        return ApiCaptioner(settings, model_id, reference_dir)
    raise InvalidInput(f"Unknown caption backend {backend!r}; use 'local' or 'api'")


def process_episode(
    episode_path: Path,
    captioner: Captioner,
    force: bool = False,
    limit: int | None = None,
) -> EpisodeCaptions:
    episode_name = episode_path.name
    result = EpisodeCaptions(episode=episode_name, folder=episode_path)
    folders = chunk_folders(episode_path)
    if not folders:
        result.warnings.append(f"No chunk folders found in {episode_path}")
        return result
    if limit is not None:
        folders = folders[:limit]

    aggregate: dict[str, dict] = {}
    for folder in folders:
        target = folder / "structured_caption.txt"
        if target.is_file() and target.stat().st_size and not force:
            result.captions.append(CaptionResult(chunk=folder.name, caption=None))
            try:
                existing = target.read_text(encoding="utf-8-sig")
            except (OSError, UnicodeError):
                existing = ""
            if existing:
                body = existing.split("\n\n", 1)[-1].strip()
                aggregate[folder.name] = {
                    "caption": body,
                    "episode": episode_name,
                    "chunk": folder.name,
                }
            continue
        try:
            captioned = captioner.caption(folder, episode_name)
            caption = validate_caption(captioned.caption or "")
            write_caption(
                folder,
                caption_file_text(
                    episode_name, folder.name, captioned.subtitles or "", caption
                ),
            )
            captioned.caption = caption
            result.captions.append(captioned)
            aggregate[folder.name] = {
                "caption": caption,
                "subtitles": captioned.subtitles or "",
                "episode": episode_name,
                "chunk": folder.name,
            }
        except SearchyError as exc:
            result.captions.append(CaptionResult(chunk=folder.name, error=str(exc)))
            result.warnings.append(f"{folder.name}: {exc}")
    if aggregate:
        write_episode_aggregate(episode_path, aggregate)
    return result


def process_collection(
    root: Path,
    settings: Settings,
    model_id: str | None = None,
    reference_dir: Path | None = DEFAULT_REFERENCE_DIR,
    force: bool = False,
    limit: int | None = None,
    episodes: int | None = None,
    backend: str | None = None,
) -> list[EpisodeCaptions]:
    if not root.is_dir():
        raise InvalidInput(f"Chunked dataset folder does not exist: {root}")
    if (root / "episodes_splitted").is_dir():
        root = root / "episodes_splitted"
    folders = sorted(
        path for path in root.iterdir() if path.is_dir() and chunk_folders(path)
    )
    if episodes is not None:
        if episodes < 1:
            raise InvalidInput("Episode limit must be at least 1")
        folders = folders[:episodes]
    if not folders:
        raise InvalidInput(f"No episode folders with chunks found in {root}")

    captioner = build_captioner(
        settings, backend or settings.caption_backend, model_id, reference_dir
    )
    return [process_episode(folder, captioner, force, limit) for folder in folders]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate structured_caption.txt for prepared chunks with a local VLM"
    )
    parser.add_argument(
        "root", type=Path, nargs="?", default=None, help="Chunked dataset root (default IMPORT_ROOT)"
    )
    parser.add_argument(
        "--backend",
        choices=("api", "local"),
        default=None,
        help="caption backend (default CAPTION_BACKEND)",
    )
    parser.add_argument(
        "--model", default=None, help="Model id; defaults to the backend's own choice"
    )
    parser.add_argument(
        "--references", type=Path, default=DEFAULT_REFERENCE_DIR, help="Character portrait folder"
    )
    parser.add_argument("--episodes", type=int, default=None, help="Caption at most N episodes")
    parser.add_argument("--limit", type=int, default=None, help="Caption at most N chunks each")
    parser.add_argument("--force", action="store_true", help="Re-caption chunks that already exist")
    args = parser.parse_args()

    settings = Settings()
    results = process_collection(
        args.root or settings.import_root,
        settings,
        args.model,
        args.references,
        args.force,
        args.limit,
        args.episodes,
        args.backend,
    )
    for result in results:
        done = sum(1 for item in result.captions if item.caption)
        failed = sum(1 for item in result.captions if item.error)
        kept = len(result.captions) - done - failed
        print(f"{result.episode}: {done} captioned, {kept} kept, {failed} failed")
        for warning in result.warnings:
            print(f"  warning: {warning}")


if __name__ == "__main__":
    main()
