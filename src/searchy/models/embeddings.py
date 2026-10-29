import math
from pathlib import Path
from threading import Lock
from typing import Any

from searchy.core.config import Settings
from searchy.core.errors import SearchyError


class LocalEmbeddings:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.model_id = settings.embedding_model_id
        self._model: Any = None
        self._lock = Lock()

    def _load(self):
        if self._model is None:
            with self._lock:
                if self._model is None:
                    try:
                        import torch
                        from sentence_transformers import SentenceTransformer
                    except (ImportError, OSError):
                        raise SearchyError(
                            "Local embeddings require uv sync --extra models and working native model libraries"
                        ) from None
                    try:
                        self._model = SentenceTransformer(
                            self.model_id,
                            device=self.settings.embedding_device,
                            cache_folder=str(self.settings.model_cache_dir.resolve()),
                            token=self.settings.hf_token.get_secret_value() or None,
                            model_kwargs={"torch_dtype": torch.float32},
                        )
                    except Exception:
                        raise SearchyError(
                            f"Cannot load embedding model '{self.model_id}'. Check model access, "
                            "network/cache, HF_TOKEN and accepted model license on Hugging Face."
                        ) from None
        return self._model

    @property
    def dimension(self) -> int:
        model = self._load()
        get_dimension = (
            getattr(model, "get_embedding_dimension", None)
            or model.get_sentence_embedding_dimension
        )
        dimension = get_dimension()
        if not dimension:
            raise SearchyError("Embedding model does not declare a vector dimension")
        return int(dimension)

    def _encode(self, values: list[Any], method: str) -> list[list[float]]:
        if not values:
            return []
        model = self._load()
        try:
            vectors = getattr(model, method)(
                values,
                batch_size=self.settings.embedding_batch_size,
                normalize_embeddings=True,
                show_progress_bar=False,
                convert_to_numpy=True,
            ).tolist()
        except Exception:
            raise SearchyError(f"Embedding inference failed for '{self.model_id}'") from None
        if len(vectors) != len(values) or any(
            len(v) != self.dimension or not all(math.isfinite(x) for x in v) for v in vectors
        ):
            raise SearchyError("Embedding model returned invalid vectors")
        return vectors

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._encode(texts, "encode_document")

    def embed_query(self, text: str) -> list[float]:
        return self._encode([text], "encode_query")[0]


class VisualEmbeddings(LocalEmbeddings):
    def __init__(self, settings: Settings):
        super().__init__(settings)
        self.model_id = settings.visual_model_id

    def embed_images(self, paths: list[Path]) -> list[list[float]]:
        if not paths:
            return []
        try:
            from PIL import Image
        except ImportError:
            raise SearchyError("Visual embeddings require: uv sync --extra models") from None
        images = []
        try:
            for path in paths:
                with Image.open(path) as image:
                    images.append(image.convert("RGB"))
            return self._encode(images, "encode")
        except OSError:
            raise SearchyError("A representative frame could not be read") from None
        finally:
            for image in images:
                image.close()

    def embed_query(self, text: str) -> list[float]:
        return self._encode([text], "encode")[0]
