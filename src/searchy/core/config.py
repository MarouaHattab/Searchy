from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    data_dir: Path = Path("var")
    import_root: Path = Path("data/episodes_splitted")
    character_reference_dir: Path | None = Path("data/meta")
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: SecretStr = SecretStr("")
    neo4j_database: str = "neo4j"
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: SecretStr = SecretStr("")
    qdrant_collection_name: str = "searchy_scenes"
    llm_provider: Literal["GOOGLE_GENAI", "GROQ"] = "GOOGLE_GENAI"
    llm_model_id: str = "gemini-2.5-flash-lite"
    gemini_api_key: SecretStr = SecretStr("")
    groq_api_key: SecretStr = SecretStr("")
    embedding_provider: Literal["LOCAL_EMBEDDING"] = "LOCAL_EMBEDDING"
    embedding_model_id: str = "google/embeddinggemma-300m"
    embedding_device: str = "cpu"
    embedding_batch_size: int = Field(default=16, ge=1, le=256)
    model_cache_dir: Path = Path(".cache/models")
    hf_token: SecretStr = SecretStr("")
    hf_hub_enable_hf_transfer: bool = False
    visual_enabled: bool = False
    visual_model_id: str = "clip-ViT-B-32"
    whisper_model_id: str = "base"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
    max_upload_mb: int = Field(default=2048, ge=1)
    max_video_seconds: int = Field(default=14400, ge=1)
    scene_min_seconds: float = Field(default=8, gt=0)
    scene_max_seconds: float = Field(default=60, gt=0)
    frames_per_scene: int = Field(default=3, ge=1, le=8)
    provider_timeout_seconds: float = Field(default=90, gt=0)
    vlm_max_images: int | None = Field(default=None, ge=1, le=32)
    worker_poll_seconds: float = Field(default=2, gt=0)
    job_lease_seconds: int = Field(default=120, ge=30)
    candidate_limit: int = Field(default=80, ge=10, le=500)
    semantic_min_score: float = Field(default=0.45, ge=-1, le=1)
    visual_min_score: float = Field(default=0.23, ge=-1, le=1)
    api_key: SecretStr = SecretStr("")
    cors_origins: list[str] = ["http://127.0.0.1:5173", "http://localhost:5173"]

    @property
    def database_path(self) -> Path:
        return self.data_dir / "searchy.sqlite3"
