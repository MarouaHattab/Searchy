import hashlib
import math
from pathlib import Path
from typing import Any

import httpx
from qdrant_client import QdrantClient, models

from searchy.core.config import Settings
from searchy.core.errors import SearchyError
from searchy.domain import Candidate, Scene, stable_id


def _name(kind: str, identity: str) -> str:
    return f"{kind}_{hashlib.sha256(identity.encode()).hexdigest()[:16]}"


def _windows(text: str) -> list[str]:
    words = text.split()
    windows = []
    for offset in range(0, len(words), 80):
        windows.append(" ".join(words[offset : offset + 100]))
        if offset + 100 >= len(words):
            break
    return windows


def _scene_filter(scene_ids: list[str], keep_ids: list[str] | None = None) -> models.Filter:
    return models.Filter(
        must=[models.FieldCondition(key="scene_id", match=models.MatchAny(any=scene_ids))],
        must_not=[models.HasIdCondition(has_id=keep_ids)] if keep_ids else None,
    )


class VectorStore:
    def __init__(self, settings: Settings, embeddings: Any, visual: Any = None, client: Any = None):
        self.settings = settings
        self.embeddings = embeddings
        self.visual = visual
        self.text_vector_name = _name(
            "text", f"{settings.embedding_provider}:{embeddings.model_id}"
        )
        visual_id = visual.model_id if visual is not None else settings.visual_model_id
        self.visual_vector_name = _name("visual", f"sentence-transformers:{visual_id}")
        self._dimensions: dict[str, int] = {}
        self._indexes_created = False
        self.client = (
            client
            if client is not None
            else QdrantClient(
                url=settings.qdrant_url,
                api_key=settings.qdrant_api_key.get_secret_value() or None,
                timeout=15,
                check_compatibility=False,
                limits=httpx.Limits(
                    max_connections=10, max_keepalive_connections=10, keepalive_expiry=30
                ),
            )
        )

    @property
    def _visual_enabled(self) -> bool:
        return self.settings.visual_enabled or self.visual is not None

    def _configuration(self, dimensions: bool) -> dict[str, int | None]:
        vectors = {self.text_vector_name: self.embeddings.dimension if dimensions else None}
        if self._visual_enabled:
            if dimensions and self.visual is None:
                raise SearchyError(
                    "Visual embeddings are enabled but no visual model is configured"
                )
            vectors[self.visual_vector_name] = self.visual.dimension if dimensions else None
        return vectors

    def _validate_collection(self, info, dimensions: dict[str, int | None]) -> None:
        vectors = info.config.params.vectors
        compatible = isinstance(vectors, dict) and set(vectors) == set(dimensions)
        if compatible:
            compatible = all(
                value.distance == models.Distance.COSINE
                and value.size > 0
                and (dimensions[name] is None or value.size == dimensions[name])
                for name, value in vectors.items()
            )
        if not compatible:
            raise SearchyError(
                "Qdrant collection is incompatible with the configured embedding models, "
                "dimensions or cosine distance. Use a new QDRANT_COLLECTION_NAME and reindex"
            )

    def ready(self) -> None:
        try:
            collections = self.client.get_collections().collections
            if any(
                collection.name == self.settings.qdrant_collection_name
                for collection in collections
            ):
                dimensions = self._dimensions or self._configuration(dimensions=False)
                self._validate_collection(
                    self.client.get_collection(self.settings.qdrant_collection_name), dimensions
                )
        except SearchyError:
            raise
        except Exception:
            raise SearchyError(
                "Qdrant is unavailable. Check QDRANT_URL and service credentials"
            ) from None

    def ensure_collection(self) -> None:
        try:
            dimensions = self._configuration(dimensions=True)
            if any(not isinstance(size, int) or size <= 0 for size in dimensions.values()):
                raise SearchyError("An embedding model returned an invalid vector dimension")
            if not self.client.collection_exists(self.settings.qdrant_collection_name):
                self.client.create_collection(
                    self.settings.qdrant_collection_name,
                    vectors_config={
                        name: models.VectorParams(size=size, distance=models.Distance.COSINE)
                        for name, size in dimensions.items()
                    },
                )
                self._indexes_created = False
            info = self.client.get_collection(self.settings.qdrant_collection_name)
            self._validate_collection(info, dimensions)
            if not self._indexes_created:
                for field in ("scene_id", "collection_id"):
                    if field not in info.payload_schema:
                        self.client.create_payload_index(
                            collection_name=self.settings.qdrant_collection_name,
                            field_name=field,
                            field_schema=models.PayloadSchemaType.KEYWORD,
                            wait=True,
                        )
                self._indexes_created = True
            self._dimensions = dimensions
        except SearchyError:
            raise
        except Exception:
            raise SearchyError("Cannot initialize the Qdrant scene collection") from None

    def _validate_vectors(self, vectors: list[list[float]], count: int, dimension: int) -> None:
        if len(vectors) != count or any(
            len(vector) != dimension
            or not all(math.isfinite(value) for value in vector)
            or not any(value != 0 for value in vector)
            for vector in vectors
        ):
            raise SearchyError("The embedding model returned invalid vectors")

    def _frame_vector(self, scene: Scene) -> list[float] | None:
        if not self._visual_enabled or not scene.frames:
            return None
        paths = [Path(frame.path) for frame in scene.frames]
        if any(not path.is_file() for path in paths):
            raise SearchyError("A scene's representative frame is unavailable for visual indexing")
        vectors = self.visual.embed_images(paths)
        dimension = self._dimensions[self.visual_vector_name]
        self._validate_vectors(vectors, len(paths), dimension)
        mean = [
            sum(vector[index] for vector in vectors) / len(vectors) for index in range(dimension)
        ]
        norm = math.sqrt(sum(value * value for value in mean))
        if norm == 0:
            raise SearchyError("Visual frame embeddings have a zero mean vector")
        return [value / norm for value in mean]

    def upsert(self, scenes: list[Scene]) -> None:
        if not scenes:
            return
        self.ensure_collection()
        try:
            batch_size = self.settings.embedding_batch_size
            for offset in range(0, len(scenes), batch_size):
                batch = scenes[offset : offset + batch_size]
                documents = []
                for scene in batch:
                    narrative = scene.model_copy(update={"dialogue": []}).search_text()
                    dialogue = "\n".join(
                        f"{item.speaker}: {item.text}" if item.speaker else item.text
                        for item in scene.dialogue
                    )
                    if not narrative and not dialogue:
                        raise SearchyError(
                            "A scene has no searchable description, observations or dialogue"
                        )
                    for index, text in enumerate(_windows(narrative or dialogue)):
                        point_id = (
                            scene.scene_id
                            if index == 0
                            else stable_id(f"{scene.scene_id}:text:{index}")
                        )
                        documents.append((scene, point_id, "text", text))
                    if narrative:
                        for index, text in enumerate(_windows(dialogue)):
                            identity = (
                                f"{scene.scene_id}:dialogue"
                                if index == 0
                                else f"{scene.scene_id}:dialogue:{index}"
                            )
                            documents.append((scene, stable_id(identity), "dialogue", text))
                texts = [text for _, _, _, text in documents]
                embeddings = self.embeddings.embed_documents(texts)
                self._validate_vectors(
                    embeddings, len(documents), self._dimensions[self.text_vector_name]
                )
                points = []
                for (scene, point_id, kind, text), embedding in zip(
                    documents, embeddings, strict=True
                ):
                    vectors = {self.text_vector_name: embedding}
                    visual_vector = (
                        self._frame_vector(scene) if point_id == scene.scene_id else None
                    )
                    if visual_vector is not None:
                        vectors[self.visual_vector_name] = visual_vector
                    points.append(
                        models.PointStruct(
                            id=point_id,
                            vector=vectors,
                            payload={
                                "scene_id": scene.scene_id,
                                "video_id": scene.video_id,
                                "collection_id": scene.collection_id,
                                "episode_id": scene.episode_id,
                                "start": scene.start,
                                "end": scene.end,
                                "text": text,
                                "kind": kind,
                            },
                        )
                    )
                self.client.upsert(self.settings.qdrant_collection_name, points=points, wait=True)
                self.client.delete(
                    collection_name=self.settings.qdrant_collection_name,
                    points_selector=models.FilterSelector(
                        filter=_scene_filter(
                            [scene.scene_id for scene in batch], [str(point.id) for point in points]
                        )
                    ),
                    wait=True,
                )
        except SearchyError:
            raise
        except Exception:
            raise SearchyError(
                "Qdrant scene indexing failed. The ingestion job can be retried"
            ) from None

    def search(
        self, query: str, collection_id: str | None, limit: int, visual: bool = False
    ) -> list[Candidate]:
        if visual and not self._visual_enabled:
            return []
        try:
            if not self.client.collection_exists(self.settings.qdrant_collection_name):
                return []
            self.ensure_collection()
            provider = self.visual if visual else self.embeddings
            vector_name = self.visual_vector_name if visual else self.text_vector_name
            vector = provider.embed_query(query)
            self._validate_vectors([vector], 1, self._dimensions[vector_name])
            query_filter = (
                models.Filter(
                    must=[
                        models.FieldCondition(
                            key="collection_id", match=models.MatchValue(value=collection_id)
                        )
                    ]
                )
                if collection_id is not None
                else None
            )
            candidates = []
            seen = set()
            offset = 0
            page_size = max(limit, 32)
            while len(candidates) < limit:
                points = self.client.query_points(
                    collection_name=self.settings.qdrant_collection_name,
                    query=vector,
                    using=vector_name,
                    query_filter=query_filter,
                    limit=page_size,
                    offset=offset,
                    score_threshold=self.settings.visual_min_score
                    if visual
                    else self.settings.semantic_min_score,
                    with_payload=True,
                    with_vectors=False,
                ).points
                for point in points:
                    scene_id = point.payload["scene_id"]
                    if scene_id not in seen:
                        seen.add(scene_id)
                        candidates.append(
                            Candidate(
                                scene_id=scene_id,
                                score=point.score,
                                channel="visual" if visual else "text",
                                evidence=["Visual similarity to sampled frames"]
                                if visual
                                else [point.payload["text"]],
                            )
                        )
                    if len(candidates) == limit:
                        break
                if len(points) < page_size:
                    break
                offset += page_size
            return candidates
        except SearchyError:
            raise
        except Exception:
            raise SearchyError(
                "Qdrant scene search failed. Check the vector service and model"
            ) from None

    def close(self) -> None:
        self.client.close()

    def delete_scenes(self, scene_ids: list[str]) -> None:
        if not scene_ids:
            return
        try:
            if self.client.collection_exists(self.settings.qdrant_collection_name):
                self.client.delete(
                    collection_name=self.settings.qdrant_collection_name,
                    points_selector=models.FilterSelector(filter=_scene_filter(scene_ids)),
                    wait=True,
                )
        except Exception:
            raise SearchyError("Qdrant could not remove obsolete scene vectors") from None

    def indexed_scene_ids(self, scene_ids: list[str]) -> set[str]:
        if not scene_ids:
            return set()
        try:
            if not self.client.collection_exists(self.settings.qdrant_collection_name):
                return set()
            present = set()
            for offset in range(0, len(scene_ids), 100):
                points = self.client.retrieve(
                    collection_name=self.settings.qdrant_collection_name,
                    ids=scene_ids[offset : offset + 100],
                    with_payload=False,
                    with_vectors=False,
                )
                present.update(str(point.id) for point in points)
            return present
        except Exception:
            raise SearchyError("Qdrant could not verify indexed scene records") from None
