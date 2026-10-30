from __future__ import annotations

import hashlib
import re
import warnings
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from searchy.api.schemas import public_job
from searchy.core.config import Settings
from searchy.core.errors import InvalidInput, SearchyError
from searchy.models.faces import OpenCVFaces
from searchy.storage.characters import CharacterStore
from searchy.storage.metadata import MetadataStore


class CharacterService:
    def __init__(
        self,
        settings: Settings,
        metadata: MetadataStore,
        store: CharacterStore | None = None,
        faces=None,
    ):
        self.settings = settings
        self.metadata = metadata
        self.store = store or CharacterStore(settings.database_path)
        self.root = (settings.data_dir / "characters").resolve()
        detector = getattr(settings, "face_detector_path", None)
        recognizer = getattr(settings, "face_recognizer_path", None)
        self.faces = faces or (
            OpenCVFaces(detector, recognizer) if detector and recognizer else None
        )

    def public(self, character: dict) -> dict:
        _, records, _ = self.metadata.catalog_records()
        scenes = [
            scene
            for scene, indexed in records
            if indexed and character["id"] in scene.character_ids
        ]
        verified = sum(
            any(
                observation.provenance.verified
                and character["id"] in {observation.character_id, observation.subject_id}
                for observation in scene.observations
            )
            for scene in scenes
        )
        references = [
            {key: reference[key] for key in ("id", "width", "height", "validation", "error")}
            | {"url": f"/api/characters/{character['id']}/references/{reference['id']}"}
            for reference in character["references"]
        ]
        return {
            **{
                key: character[key]
                for key in (
                    "id",
                    "name",
                    "description",
                    "collection_id",
                    "video_id",
                    "revision",
                    "status",
                    "recognition_status",
                    "created_at",
                    "updated_at",
                )
            },
            "references": references,
            "reference_url": references[0]["url"] if references else None,
            "identity_status": "reference" if references else "unverified",
            "scene_count": len(scenes),
            "video_count": len({scene.video_id for scene in scenes}),
            "verified_scene_count": verified,
            "origin": "custom",
        }

    def _get(self, character_id: str) -> dict:
        character = self.store.get(character_id)
        if character is None:
            raise SearchyError("Character not found", 404)
        return character

    def get(self, character_id: str) -> dict:
        return self.public(self._get(character_id))

    def list(self, collection_id: str | None = None, video_id: str | None = None) -> list[dict]:
        return [self.public(character) for character in self.store.list(collection_id, video_id)]

    @staticmethod
    def _name(name: str) -> str:
        name = " ".join(name.split())
        if not 1 <= len(name) <= 100:
            raise InvalidInput("Character name must contain 1-100 characters")
        return name

    def create(
        self,
        name: str,
        description: str = "",
        collection_id: str = "uploads",
        video_id: str | None = None,
    ) -> dict:
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", collection_id):
            raise InvalidInput(
                "Collection ID must contain 1-80 letters, digits, underscores or hyphens"
            )
        if len(description) > 2000:
            raise InvalidInput("Character description must not exceed 2000 characters")
        if video_id:
            video = self.metadata.get_video(video_id)
            if video is None:
                raise SearchyError("Video not found", 404)
            if video.collection_id != collection_id:
                raise InvalidInput("Selected video does not belong to this collection")
        return self.public(
            self.store.create(self._name(name), description.strip(), collection_id, video_id)
        )

    def update(
        self, character_id: str, name: str | None = None, description: str | None = None
    ) -> dict:
        character = self._get(character_id)
        values = {}
        if name is not None:
            values["name"] = self._name(name)
        values["revision"] = character["revision"] + int(
            values.get("name", character["name"]) != character["name"]
        )
        if description is not None:
            if len(description) > 2000:
                raise InvalidInput("Character description must not exceed 2000 characters")
            values["description"] = description.strip()
        if not self.store.update(character_id, values, character["revision"]):
            raise SearchyError("Character changed during editing. Reload and try again.", 409)
        if character["status"] in {"queued", "processing"} and character["references"]:
            self._queue(self._get(character_id))
        return self.get(character_id)

    @staticmethod
    def _normalize(content: bytes) -> tuple[bytes, int, int]:
        if not 0 < len(content) <= 10 * 1024 * 1024:
            raise InvalidInput("Reference images must be nonempty and no larger than 10 MB")
        try:
            from PIL import Image, ImageOps, UnidentifiedImageError
        except ImportError:
            raise SearchyError(
                "Reference image validation requires: uv sync --extra models"
            ) from None
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(BytesIO(content)) as image:
                    if image.format not in {"JPEG", "PNG", "WEBP"}:
                        raise InvalidInput("Upload a JPEG, PNG or WebP reference image")
                    if image.width * image.height > 12_000_000 or min(image.size) < 32:
                        raise InvalidInput(
                            "Reference images must have at least 32 pixels per side and at most 12 megapixels"
                        )
                    if getattr(image, "n_frames", 1) != 1:
                        raise InvalidInput(
                            "Use a still reference image rather than an animated image"
                        )
                    image.load()
                    normalized = ImageOps.exif_transpose(image).convert("RGB")
                    output = BytesIO()
                    normalized.save(output, format="JPEG", quality=90)
                    return output.getvalue(), normalized.width, normalized.height
        except (
            OSError,
            UnidentifiedImageError,
            Image.DecompressionBombError,
            Image.DecompressionBombWarning,
            ValueError,
        ):
            raise InvalidInput("Reference image is corrupted or cannot be decoded safely") from None

    def _queue(self, character: dict) -> dict:
        try:
            self.store.update(character["id"], {"status": "queued"}, character["revision"])
            job = self.metadata.create_job(
                "character_references",
                {
                    "character_id": character["id"],
                    "revision": character["revision"],
                    "collection_id": character["collection_id"],
                    "title": f"Prepare {character['name']} references",
                },
            )
            return public_job(job)
        except Exception:
            self.store.update(character["id"], {"status": "failed"}, character["revision"])
            raise

    def add_references(self, character_id: str, images: list[bytes]) -> dict:
        original = self._get(character_id)
        if not 1 <= len(images) <= 5:
            raise InvalidInput("Upload between one and five reference images")
        normalized = [self._normalize(image) for image in images]
        directory = self.root / character_id
        directory.mkdir(parents=True, exist_ok=True)
        existing = {reference["digest"] for reference in original["references"]}
        references = {}
        try:
            for content, width, height in normalized:
                digest = hashlib.sha256(content).hexdigest()
                if digest in existing or digest in references:
                    continue
                identifier = str(uuid4())
                path = directory / f"{identifier}.jpg"
                path.write_bytes(content)
                references[digest] = {
                    "id": identifier,
                    "digest": digest,
                    "path": str(path),
                    "width": width,
                    "height": height,
                }
            character = self.store.add_references(character_id, list(references.values()))
        except Exception:
            for reference in references.values():
                Path(reference["path"]).unlink(missing_ok=True)
            raise
        retained = {reference["path"] for reference in character["references"]}
        for reference in references.values():
            if reference["path"] not in retained:
                Path(reference["path"]).unlink(missing_ok=True)
        job = self._queue(character) if character["revision"] != original["revision"] else None
        return {"character": self.get(character_id), "job": job}

    def reference_path(
        self, character_id: str, reference_id: str, require_exists: bool = True
    ) -> Path:
        character = self._get(character_id)
        reference = next(
            (ref for ref in character["references"] if ref["id"] == reference_id), None
        )
        if reference is None:
            raise SearchyError("Character reference not found", 404)
        path = Path(reference["path"])
        if (
            path.is_symlink()
            or not path.resolve().is_relative_to(self.root)
            or (require_exists and not path.is_file())
        ):
            raise SearchyError("Character reference image is unavailable", 404)
        return path

    def remove_reference(self, character_id: str, reference_id: str) -> dict:
        path = self.reference_path(character_id, reference_id, require_exists=False)
        if not self.store.remove_reference(character_id, reference_id):
            raise SearchyError("Character reference not found", 404)
        path.unlink(missing_ok=True)
        character = self._get(character_id)
        job = self._queue(character) if character["references"] else None
        return {"character": self.get(character_id), "job": job}

    def replace_reference(self, character_id: str, reference_id: str, image: bytes) -> dict:
        previous = self.reference_path(character_id, reference_id, require_exists=False)
        content, width, height = self._normalize(image)
        identifier = str(uuid4())
        path = self.root / character_id / f"{identifier}.jpg"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        try:
            character = self.store.replace_reference(
                character_id,
                reference_id,
                {
                    "id": identifier,
                    "digest": hashlib.sha256(content).hexdigest(),
                    "path": str(path),
                    "width": width,
                    "height": height,
                },
            )
        except Exception:
            path.unlink(missing_ok=True)
            raise
        previous.unlink(missing_ok=True)
        job = self._queue(character)
        return {"character": self.get(character_id), "job": job}

    def delete(self, character_id: str) -> dict:
        character = self._get(character_id)
        self.store.delete(character_id)
        for reference in character["references"]:
            path = Path(reference["path"])
            if path.resolve().is_relative_to(self.root) and not path.is_symlink():
                path.unlink(missing_ok=True)
        return {"id": character_id, "deleted": True}

    def prepare_references(self, character_id: str, revision: int) -> dict:
        character = self.store.get(character_id)
        if character is None or character["revision"] != revision:
            return {"skipped": True, "reason": "Character or references changed"}
        if not self.store.update(character_id, {"status": "processing"}, revision):
            return {"skipped": True, "reason": "Character or references changed"}
        prepared = []
        for reference in character["references"]:
            result = {"id": reference["id"], "validation": "image_validated"}
            try:
                path = self.reference_path(character_id, reference["id"])
                if self.faces:
                    encoding = self.faces.encode(path)
                    result.update(
                        validation="face_ready",
                        embedding=encoding.embedding,
                        model_id=encoding.model_id,
                    )
            except InvalidInput as exc:
                result.update(validation="rejected", error=str(exc))
            except SearchyError as exc:
                result.update(validation="failed", error=str(exc))
            prepared.append(result)
        if not self.store.save_prepared(character_id, revision, prepared):
            return {"skipped": True, "reason": "Character or references changed"}
        accepted = sum(ref["validation"] in {"image_validated", "face_ready"} for ref in prepared)
        if not accepted:
            raise InvalidInput(
                "No usable character references remain. Review the reference image errors."
            )
        return {
            "character_id": character_id,
            "revision": revision,
            "processed": len(prepared),
            "accepted": accepted,
            "rejected": len(prepared) - accepted,
            "recognition_status": "unprocessed",
        }
