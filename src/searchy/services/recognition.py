import hashlib
import json
import math
import time
from pathlib import Path

from searchy.api.schemas import public_job
from searchy.core import InvalidInput, SearchyError
from searchy.domain import Observation, Provenance, Scene, stable_id
from searchy.models import IdentityReference, OpenCVFaces, get_vision_provider
from searchy.processing import VideoProcessor


class RecognitionService:
    def __init__(self, settings, metadata, characters, graph, vectors):
        self.settings = settings
        self.metadata = metadata
        self.registry = getattr(characters, "store", characters)
        self.graph = graph
        self.vectors = vectors
        self.last_vlm_error: str | None = None
        detector = getattr(settings, "face_detector_path", None)
        recognizer = getattr(settings, "face_recognizer_path", None)
        self.faces = getattr(characters, "faces", None) or (
            OpenCVFaces(detector, recognizer) if detector and recognizer else None
        )
        with self.registry.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS character_matches (
                    id TEXT PRIMARY KEY, character_id TEXT NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
                    revision INTEGER NOT NULL, scene_id TEXT NOT NULL REFERENCES scenes(scene_id) ON DELETE CASCADE,
                    frame_key TEXT NOT NULL, frame_path TEXT NOT NULL, timestamp REAL NOT NULL,
                    method TEXT NOT NULL, model_id TEXT NOT NULL, confidence REAL NOT NULL,
                    evidence TEXT NOT NULL, qualified INTEGER NOT NULL, bounds TEXT,
                    status TEXT NOT NULL DEFAULT 'pending', index_status TEXT NOT NULL DEFAULT 'pending',
                    created_at REAL NOT NULL, updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS character_match_scene ON character_matches(character_id,scene_id);
                CREATE TABLE IF NOT EXISTS character_scans (
                    character_id TEXT NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
                    revision INTEGER NOT NULL, scene_id TEXT NOT NULL REFERENCES scenes(scene_id) ON DELETE CASCADE,
                    frame_key TEXT NOT NULL, PRIMARY KEY(character_id,revision,scene_id,frame_key)
                );
            """)
            columns = {row[1] for row in db.execute("PRAGMA table_info(character_matches)")}
            for name, declaration in (
                ("active", "INTEGER NOT NULL DEFAULT 1"),
                ("evidence_key", "TEXT NOT NULL DEFAULT ''"),
            ):
                if name not in columns:
                    db.execute(f"ALTER TABLE character_matches ADD COLUMN {name} {declaration}")

    def _get(self, character_id: str, revision: int | None = None) -> dict:
        character = self.registry.get(character_id)
        if character is None:
            raise SearchyError("Character not found", 404)
        if revision is not None and character["revision"] != revision:
            raise SearchyError("Character or references changed; start recognition again", 409)
        return character

    def start(self, character_id: str) -> dict:
        character = self._get(character_id)
        if character["status"] != "ready" or not any(
            reference["validation"] in {"image_validated", "face_ready"}
            for reference in character["references"]
        ):
            raise InvalidInput(
                "Prepare at least one usable reference image before recognizing this character"
            )
        for job in self.metadata.list_jobs(200):
            if (
                job["kind"] == "character_recognition"
                and job["status"] in {"queued", "running"}
                and job["payload"].get("character_id") == character_id
                and job["payload"].get("revision") == character["revision"]
            ):
                return public_job(job)
        job = self.metadata.create_job(
            "character_recognition",
            {
                "character_id": character_id,
                "revision": character["revision"],
                "collection_id": character["collection_id"],
                "title": f"Recognize {character['name']}",
            },
        )
        self.registry.update(character_id, {"recognition_status": "queued"}, character["revision"])
        return public_job(job)

    def matches(self, character_id: str, limit: int = 100, offset: int = 0) -> list[dict]:
        character = self._get(character_id)
        with self.registry.connect() as db:
            rows = db.execute(
                "SELECT * FROM character_matches WHERE character_id=? AND revision=? AND active=1 ORDER BY timestamp,scene_id,id LIMIT ? OFFSET ?",
                (character_id, character["revision"], min(200, max(1, limit)), max(0, offset)),
            ).fetchall()
        return [self._public(dict(row)) for row in rows]

    @staticmethod
    def _public(row: dict) -> dict:
        keys = (
            "id",
            "character_id",
            "revision",
            "scene_id",
            "timestamp",
            "method",
            "model_id",
            "confidence",
            "evidence",
            "status",
            "index_status",
            "created_at",
            "updated_at",
        )
        return {key: row[key] for key in keys} | {
            "qualified": bool(row["qualified"]),
            "verified": row["status"] == "accepted",
            "frame_url": f"/api/characters/{row['character_id']}/matches/{row['id']}/frame",
        }

    def frame_path(self, character_id: str, match_id: str) -> Path:
        character = self._get(character_id)
        with self.registry.connect() as db:
            row = db.execute(
                "SELECT * FROM character_matches WHERE id=? AND character_id=? AND revision=? AND active=1",
                (match_id, character_id, character["revision"]),
            ).fetchone()
        if row is None:
            raise SearchyError("Character match not found", 404)
        scene = self.metadata.get_scene(row["scene_id"])
        path = Path(row["frame_path"])
        if scene is None or path.is_symlink() or not path.is_file():
            raise SearchyError("Character match frame is unavailable", 404)
        registered = any(
            Path(frame.path).resolve() == path.resolve() and frame.timestamp == row["timestamp"]
            for frame in scene.frames
        )
        generated = path.resolve().is_relative_to(
            (
                self.settings.data_dir / "processing" / "recognition_frames" / scene.scene_id
            ).resolve()
        )
        if not (registered or generated):
            raise SearchyError("Character match frame is unavailable", 404)
        if (
            row["evidence_key"]
            and row["evidence_key"]
            != hashlib.sha256(path.read_bytes() + repr(row["timestamp"]).encode()).hexdigest()
        ):
            raise SearchyError("Character match frame is unavailable", 404)
        return path

    def _rows(self, character_id: str, scene_id: str, revision: int) -> list[dict]:
        with self.registry.connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT * FROM character_matches WHERE character_id=? AND scene_id=? AND revision=? AND active=1 ORDER BY timestamp,id",
                    (character_id, scene_id, revision),
                )
            ]

    def _frames(self, scene: Scene) -> list:
        frames = [
            frame
            for frame in scene.frames
            if Path(frame.path).is_file()
            and scene.start is not None
            and scene.start <= frame.timestamp <= scene.end
        ]
        if frames or not scene.media or scene.start is None or not Path(scene.media.path).is_file():
            return frames
        processor = VideoProcessor(self.settings)
        path = Path(scene.media.path)
        start = scene.media.start_offset
        duration = scene.media.duration or processor.probe(path).duration
        end = min(duration, start + scene.end - scene.start)
        if end <= start:
            return []
        cache = self.settings.data_dir / "processing" / "recognition_frames" / scene.scene_id
        frames = processor.sample_frames(path, start, end, cache)
        scene.frames = [
            frame.model_copy(update={"timestamp": scene.start + frame.timestamp - start})
            for frame in frames
        ]
        return scene.frames

    @staticmethod
    def _embedding(reference: dict) -> list[float] | None:
        value = reference.get("embedding")
        try:
            vector = json.loads(value) if isinstance(value, str) else value
            if not vector or not all(math.isfinite(float(item)) for item in vector):
                return None
            norm = math.sqrt(sum(float(item) ** 2 for item in vector))
            return [float(item) / norm for item in vector] if norm else None
        except (ValueError, TypeError):
            return None

    def _candidates(
        self, character: dict, scene: Scene, frame, others: list[dict], face_ready: bool
    ) -> list[dict]:
        """SFace when a reference has an embedding, the vision model otherwise.

        The vision path costs a network call and can fail on its own (rate limit,
        provider error, unusable response). That must not abort the whole job, so
        it degrades to no candidate for this frame.
        """
        if face_ready:
            return self._face_candidates(character, frame, others)
        try:
            return self._vlm_candidates(character, scene, frame, others)
        except InvalidInput:
            raise
        except SearchyError as exc:
            self.last_vlm_error = str(exc)
            return []

    def _face_candidates(self, character: dict, frame, others: list[dict]) -> list[dict]:
        result = []
        threshold = getattr(self.settings, "face_match_threshold", 0.5)
        minimum_margin = getattr(self.settings, "face_match_margin", 0.08)
        for face in self.faces.detect(Path(frame.path)):
            scores = {}
            for candidate in others:
                values = []
                for reference in candidate["references"]:
                    vector = self._embedding(reference)
                    if (
                        reference.get("model_id") == face.model_id
                        and vector is not None
                        and len(vector) == len(face.embedding)
                    ):
                        values.append(
                            sum(a * b for a, b in zip(vector, face.embedding, strict=True))
                        )
                if values:
                    scores[candidate["id"]] = max(values)
            score = scores.get(character["id"], -1)
            if score < 0.25:
                continue
            runner_up = max(
                (value for key, value in scores.items() if key != character["id"]), default=0
            )
            margin = score - runner_up
            result.append(
                {
                    "method": "sface_reference_comparison",
                    "model_id": face.model_id,
                    "confidence": max(0, min(1, score)),
                    "qualified": score >= threshold and margin >= minimum_margin,
                    "bounds": list(face.bounds),
                    "evidence": f"A detected face has cosine similarity {score:.3f} to this character's reference embeddings; separation from other registered identities is {margin:.3f}. This is a model candidate, not a verified identity.",
                }
            )
        return result

    def _vlm_candidates(
        self, character: dict, scene: Scene, frame, others: list[dict]
    ) -> list[dict]:
        available = [
            (candidate, reference)
            for candidate in others
            if candidate["status"] == "ready"
            for reference in candidate["references"]
            if reference["validation"] in {"image_validated", "face_ready"}
            and Path(reference["path"]).is_file()
        ]
        references = [
            IdentityReference(
                candidate["id"], candidate["name"], Path(reference["path"]), candidate["revision"]
            )
            for candidate, reference in available
        ]
        if not any(reference.character_id == character["id"] for reference in references):
            raise InvalidInput("No usable character reference images are available")
        maximum = self.settings.vlm_max_images or (
            3 if self.settings.caption_provider == "GROQ" else 10
        )
        own_references = [ref for ref in references if ref.character_id == character["id"]]
        peers_omitted = len(references) > maximum - 1 and any(
            reference.character_id != character["id"] for reference in references
        )
        if len(references) > maximum - 1:
            references = own_references
        own_digests = {
            hashlib.sha256(Path(reference["path"]).read_bytes()).hexdigest()
            for candidate, reference in available
            if candidate["id"] == character["id"]
        }
        own_embeddings = [
            (reference.get("model_id"), self._embedding(reference))
            for candidate, reference in available
            if candidate["id"] == character["id"] and self._embedding(reference)
        ]
        ambiguous = False
        for candidate, reference in available:
            if candidate["id"] == character["id"]:
                continue
            vector = self._embedding(reference)
            if hashlib.sha256(
                Path(reference["path"]).read_bytes()
            ).hexdigest() in own_digests or any(
                model is not None
                and model == reference.get("model_id")
                and vector is not None
                and len(embedding) == len(vector)
                and sum(a * b for a, b in zip(embedding, vector, strict=True)) >= 0.995
                for model, embedding in own_embeddings
            ):
                ambiguous = True
                break
        provider = get_vision_provider(
            self.settings,
            references=references,
            provider=self.settings.caption_provider,
            model_id=self.settings.caption_api_model_id or None,
        )
        _, observations = provider.analyze([frame], [], scene.start, scene.end)
        candidates = [
            observation
            for observation in observations
            if observation.kind == "character" and observation.character_id == character["id"]
        ]
        if not candidates:
            return []
        strongest = max(candidates, key=lambda item: item.provenance.confidence or 0)
        return [
            {
                "method": "vlm_reference_comparison",
                "model_id": strongest.provenance.model or self.settings.caption_api_model_id,
                "confidence": strongest.provenance.confidence or 0,
                "qualified": not ambiguous
                and not peers_omitted
                and (strongest.provenance.confidence or 0)
                >= getattr(self.settings, "vlm_identity_min_confidence", 0.85),
                "bounds": None,
                "evidence": strongest.evidence
                + " Identity is an unverified comparison with the supplied character references."
                + (
                    " Ambiguous identity: another registered character has an identical reference image or near-identical face embedding; human review is required."
                    if ambiguous
                    else ""
                )
                + (
                    " The image budget could not include competing registered identities; human review is required."
                    if peers_omitted
                    else ""
                ),
            }
        ]

    def _scan_signature(self, others: list[dict]) -> str:
        def file_hash(path):
            candidate = Path(path) if path else None
            return (
                hashlib.sha256(candidate.read_bytes()).hexdigest()
                if candidate and candidate.is_file()
                else None
            )

        signature = {
            "engine": "scoped-character-recognition-v3",
            "face_backend": type(self.faces).__qualname__ if self.faces else None,
            "face_detector": file_hash(getattr(self.settings, "face_detector_path", None)),
            "face_recognizer": file_hash(getattr(self.settings, "face_recognizer_path", None)),
            "face_threshold": getattr(self.settings, "face_match_threshold", 0.5),
            "face_margin": getattr(self.settings, "face_match_margin", 0.08),
            "vlm_provider": self.settings.caption_provider,
            "vlm_model": self.settings.caption_api_model_id,
            "vlm_images": self.settings.vlm_max_images,
            "vlm_threshold": getattr(self.settings, "vlm_identity_min_confidence", 0.85),
            "characters": [
                {
                    "id": candidate["id"],
                    "revision": candidate["revision"],
                    "status": candidate["status"],
                    "video_id": candidate["video_id"],
                    "references": [
                        {
                            "hash": file_hash(reference["path"]),
                            "validation": reference["validation"],
                            "model_id": reference.get("model_id"),
                            "embedding": self._embedding(reference),
                        }
                        for reference in candidate["references"]
                    ],
                }
                for candidate in sorted(others, key=lambda item: item["id"])
            ],
        }
        return hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest()

    def process(self, character_id: str, revision: int, progress) -> dict:
        character = self.registry.get(character_id)
        if character is None or character["revision"] != revision:
            return {"skipped": True, "reason": "Character or references changed"}
        if character["status"] != "ready":
            raise InvalidInput("Character reference processing must finish before recognition")
        self.registry.update(character_id, {"recognition_status": "processing"}, revision)
        _, records, _ = self.metadata.catalog_records()
        scenes = [
            scene
            for scene, _ in records
            if scene.collection_id == character["collection_id"]
            and (not character["video_id"] or scene.video_id == character["video_id"])
        ]
        processed = matched = skipped = 0
        try:
            for index, scene in enumerate(scenes):
                self._get(character_id, revision)
                progress(
                    0.03 + 0.9 * index / max(1, len(scenes)),
                    f"checking character evidence in scene {index + 1}/{len(scenes)}",
                )
                frames = self._frames(scene)
                if not frames:
                    skipped += 1
                    continue
                others = self.registry.list(character["collection_id"], scene.video_id)
                scope_signature = self._scan_signature(others)
                frame_keys = []
                evidence_keys = []
                for frame in frames:
                    evidence_key = hashlib.sha256(
                        Path(frame.path).read_bytes() + repr(frame.timestamp).encode()
                    ).hexdigest()
                    frame_key = hashlib.sha256(
                        (evidence_key + scope_signature).encode()
                    ).hexdigest()
                    frame_keys.append(frame_key)
                    evidence_keys.append(evidence_key)
                    with self.registry.connect() as db:
                        scanned = db.execute(
                            "SELECT 1 FROM character_scans WHERE character_id=? AND revision=? AND scene_id=? AND frame_key=?",
                            (character_id, revision, scene.scene_id, frame_key),
                        ).fetchone()
                        reviewed = db.execute(
                            "SELECT 1 FROM character_matches WHERE character_id=? AND revision=? AND scene_id=? AND evidence_key=? AND status IN ('accepted','rejected')",
                            (character_id, revision, scene.scene_id, evidence_key),
                        ).fetchone()
                    if scanned:
                        continue
                    face_ready = self.faces and any(
                        reference["validation"] == "face_ready" and self._embedding(reference)
                        for reference in character["references"]
                    )
                    candidates = [] if reviewed else self._candidates(
                        character, scene, frame, others, face_ready
                    )
                    self._get(character_id, revision)
                    with self.registry.connect() as db:
                        db.execute("BEGIN IMMEDIATE")
                        current = db.execute(
                            "SELECT revision FROM characters WHERE id=?", (character_id,)
                        ).fetchone()
                        if current is None or current[0] != revision:
                            raise SearchyError(
                                "Character or references changed; start recognition again", 409
                            )
                        now = time.time()
                        for number, candidate in enumerate(candidates):
                            match_id = stable_id(
                                f"character_match:{character_id}:{revision}:{scene.scene_id}:{frame_key}:{number}"
                            )
                            db.execute(
                                """INSERT OR IGNORE INTO character_matches(id,character_id,revision,scene_id,frame_key,frame_path,timestamp,method,model_id,confidence,evidence,qualified,bounds,created_at,updated_at,evidence_key)
                                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                                (
                                    match_id,
                                    character_id,
                                    revision,
                                    scene.scene_id,
                                    frame_key,
                                    frame.path,
                                    frame.timestamp,
                                    candidate["method"],
                                    candidate["model_id"],
                                    candidate["confidence"],
                                    candidate["evidence"],
                                    int(candidate["qualified"]),
                                    json.dumps(candidate["bounds"]),
                                    now,
                                    now,
                                    evidence_key,
                                ),
                            )
                        db.execute(
                            "INSERT OR IGNORE INTO character_scans VALUES(?,?,?,?)",
                            (character_id, revision, scene.scene_id, frame_key),
                        )
                self._get(character_id, revision)
                with self.registry.connect() as db:
                    db.execute(
                        """UPDATE character_matches SET active=CASE
                            WHEN revision=? AND (frame_key IN (SELECT value FROM json_each(?))
                                OR (status IN ('accepted','rejected') AND evidence_key IN (SELECT value FROM json_each(?))))
                            THEN 1 ELSE 0 END, updated_at=?
                            WHERE character_id=? AND scene_id=?""",
                        (
                            revision,
                            json.dumps(frame_keys),
                            json.dumps(evidence_keys),
                            time.time(),
                            character_id,
                            scene.scene_id,
                        ),
                    )
                rows = self._rows(character_id, scene.scene_id, revision)
                if rows or character_id in scene.character_ids:
                    self._apply(character, scene, rows)
                processed += 1
                matched += any(
                    row["status"] == "accepted" or (row["status"] == "pending" and row["qualified"])
                    for row in rows
                )
            self.registry.update(character_id, {"recognition_status": "ready"}, revision)
            progress(0.99, "character recognition complete")
            return {
                "character_id": character_id,
                "revision": revision,
                "processed_scenes": processed,
                "matched_scenes": matched,
                "skipped_scenes": skipped,
                "warnings": ["Scenes without accessible video or sampled frames were skipped"]
                if skipped
                else [],
            }
        except SearchyError as exc:
            if exc.status_code == 409:
                return {"skipped": True, "reason": "Character or references changed"}
            self.registry.update(character_id, {"recognition_status": "failed"}, revision)
            raise
        except Exception:
            self.registry.update(character_id, {"recognition_status": "failed"}, revision)
            raise

    @staticmethod
    def _without_identity(scene: Scene, character_id: str) -> Scene:
        scene = scene.model_copy(deep=True)
        retained = []
        for observation in scene.observations:
            if observation.character_id == character_id:
                if observation.provenance.method in {
                    "sface_reference_comparison",
                    "vlm_reference_comparison",
                    "human_reviewed_character_match",
                }:
                    continue
                observation.character_id = None
                observation.value = "unidentified person"
            retained.append(observation)
        scene.observations = retained
        for observation in scene.observations:
            if observation.subject_id == character_id:
                observation.subject_id = None
                observation.subject = None
        for line in scene.dialogue:
            if line.speaker_id == character_id:
                line.speaker_id = None
                line.speaker = None
        return scene

    def _apply(self, character: dict, scene: Scene, rows: list[dict]) -> None:
        scene = self._without_identity(scene, character["id"])
        for row in rows:
            if row["status"] == "rejected" or (
                row["status"] != "accepted" and not row["qualified"]
            ):
                continue
            accepted = row["status"] == "accepted"
            evidence = row["evidence"]
            if accepted:
                for marker in (
                    " This is a model candidate, not a verified identity.",
                    " Identity is an unverified comparison with the supplied character references.",
                ):
                    evidence = evidence.split(marker, 1)[0]
                evidence += " This appearance was human-reviewed and confirmed against the supplied reference."
            scene.observations.append(
                Observation(
                    kind="character",
                    value=character["name"],
                    character_id=character["id"],
                    evidence=evidence,
                    start=row["timestamp"],
                    end=row["timestamp"],
                    provenance=Provenance(
                        source=row["frame_path"],
                        method="human_reviewed_character_match" if accepted else row["method"],
                        model=row["model_id"],
                        confidence=row["confidence"],
                        verified=accepted,
                    ),
                )
            )
        self._persist(scene, character)
        with self.registry.connect() as db:
            db.execute(
                "UPDATE character_matches SET index_status='synced',updated_at=? WHERE character_id=? AND scene_id=? AND revision=? AND active=1",
                (time.time(), character["id"], scene.scene_id, character["revision"]),
            )

    def _persist(self, scene: Scene, character: dict) -> None:
        self._get(character["id"], character["revision"])
        video = self.metadata.get_video(scene.video_id)
        if video is None:
            raise SearchyError("Associated video no longer exists", 409)
        with self.registry.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute(
                "SELECT revision FROM characters WHERE id=?", (character["id"],)
            ).fetchone()
            if current is None or current[0] != character["revision"]:
                raise SearchyError("Character or references changed; start recognition again", 409)
            db.execute(
                "UPDATE scenes SET data=?,indexed=0,index_signature='' WHERE scene_id=?",
                (scene.model_dump_json(), scene.scene_id),
            )
        try:
            self._get(character["id"], character["revision"])
            self.graph.ensure_schema()
            self.vectors.ensure_collection()
            self.graph.upsert_scenes([scene], {video.video_id: video})
            self._get(character["id"], character["revision"])
            self.vectors.upsert([scene])
            self._get(character["id"], character["revision"])
            if self.metadata.get_scene(scene.scene_id) == scene:
                self.metadata.mark_indexed(scene.scene_id)
        except SearchyError as exc:
            if exc.status_code in {404, 409}:
                with self.registry.connect() as db:
                    db.execute(
                        "UPDATE scenes SET indexed=0,index_signature='' WHERE scene_id=?",
                        (scene.scene_id,),
                    )
            raise

    def review(self, character_id: str, match_id: str, status: str) -> dict:
        if status not in {"accepted", "rejected"}:
            raise InvalidInput("Choose accepted or rejected for a character match")
        character = self._get(character_id)
        with self.registry.connect() as db:
            row = db.execute(
                "SELECT * FROM character_matches WHERE id=? AND character_id=?",
                (match_id, character_id),
            ).fetchone()
            if row is None:
                raise SearchyError("Character match not found", 404)
            if row["revision"] != character["revision"] or not row["active"]:
                raise SearchyError(
                    "This match belongs to an older character reference revision", 409
                )
            db.execute(
                "UPDATE character_matches SET status=?,index_status='pending',updated_at=? WHERE id=?",
                (status, time.time(), match_id),
            )
        scene = self.metadata.get_scene(row["scene_id"])
        if scene is None:
            raise SearchyError("Associated scene no longer exists", 404)
        self._apply(
            character, scene, self._rows(character_id, scene.scene_id, character["revision"])
        )
        with self.registry.connect() as db:
            return self._public(
                dict(
                    db.execute("SELECT * FROM character_matches WHERE id=?", (match_id,)).fetchone()
                )
            )

    def sync_identity(self, character_id: str) -> dict:
        character = self._get(character_id)
        _, records, _ = self.metadata.catalog_records()
        updated = 0
        for scene, _ in records:
            if character_id not in scene.character_ids:
                continue
            for observation in scene.observations:
                if observation.character_id == character_id:
                    observation.value = character["name"]
                if observation.subject_id == character_id:
                    observation.subject = character["name"]
            for line in scene.dialogue:
                if line.speaker_id == character_id:
                    line.speaker = character["name"]
            self._persist(scene, character)
            updated += 1
        with self.registry.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute(
                "SELECT revision FROM characters WHERE id=?", (character_id,)
            ).fetchone()
            if current is None or current[0] != character["revision"]:
                raise SearchyError("Character changed during identity synchronization", 409)
            db.execute(
                "UPDATE character_matches SET revision=?,updated_at=? WHERE character_id=? AND revision=? AND active=1",
                (character["revision"], time.time(), character_id, character["revision"] - 1),
            )
        return {"updated_scenes": updated}

    def remove_identity(self, character_id: str, deleting: bool = False) -> dict:
        character = self._get(character_id)
        if deleting:
            with self.registry.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                result = db.execute(
                    """UPDATE characters SET revision=revision+1,status='unprocessed',
                       recognition_status='unprocessed',updated_at=? WHERE id=? AND revision=?""",
                    (time.time(), character_id, character["revision"]),
                )
                if result.rowcount != 1:
                    raise SearchyError("Character changed during deletion; try again", 409)
                db.execute(
                    "UPDATE character_matches SET active=0,updated_at=? WHERE character_id=?",
                    (time.time(), character_id),
                )
            character = self._get(character_id)
        _, records, _ = self.metadata.catalog_records()
        updated = 0
        for scene, _ in records:
            if character_id in scene.character_ids:
                self._persist(self._without_identity(scene, character_id), character)
                updated += 1
        return {"updated_scenes": updated}
