from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    data_dir: Path = Path("var")
    import_root: Path = Path("data/episodes_splitted")
    episode_media_dir: Path | None = Path("data/episodes")
    character_reference_dir: Path | None = Path("data/meta")
    face_detector_path: Path | None = None
    face_recognizer_path: Path | None = None
    face_match_threshold: float = Field(default=0.5, ge=0, le=1)
    face_match_margin: float = Field(default=0.08, ge=0, le=1)
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: SecretStr = SecretStr("")
    neo4j_database: str = "neo4j"
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: SecretStr = SecretStr("")
    qdrant_collection_name: str = "searchy_scenes"
    qdrant_episode_collection_name: str = "searchy_episodes"
    llm_provider: Literal["GOOGLE_GENAI", "GROQ", "NVIDIA_NIM"] = "GOOGLE_GENAI"
    llm_model_id: str = "gemini-3.5-flash-lite"
    caption_provider: Literal["GOOGLE_GENAI", "GROQ"] = "GOOGLE_GENAI"
    caption_api_model_id: str = ""
    gemini_api_key: SecretStr = SecretStr("")
    groq_api_key: SecretStr = SecretStr("")
    nvidia_nim_api_key: SecretStr = SecretStr("")
    nvidia_nim_base_url: str = "https://integrate.api.nvidia.com/v1"
    nvidia_nim_model: str = "nvidia/nemotron-3.5-bolt-e4b"
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
    frames_per_scene: int = Field(default=3, ge=1, le=8)
    provider_timeout_seconds: float = Field(default=90, gt=0)
    vlm_max_images: int | None = Field(default=None, ge=1, le=32)
    caption_backend: Literal["api", "local"] = "api"
    caption_model_id: str = ""
    vllm_base_url: str = ""
    vlm_identity_min_confidence: float = Field(default=0.85, ge=0, le=1)
    chat_model: str = "gemma3:1b"
    chat_context: int = Field(default=8192, ge=1024)
    chat_max_tokens: int = Field(default=1500, ge=64)
    chat_temperature: float = Field(default=0.2, ge=0, le=2)
    chat_source_limit: int = Field(default=20, ge=1, le=40)
    worker_enabled: bool = True
    worker_poll_seconds: float = Field(default=2, gt=0)
    worker_shutdown_timeout_seconds: float = Field(default=10, gt=0)
    job_lease_seconds: int = Field(default=120, ge=30)
    candidate_limit: int = Field(default=80, ge=10, le=500)
    semantic_min_score: float = Field(default=0.32, ge=-1, le=1)
    visual_min_score: float = Field(default=0.23, ge=-1, le=1)
    api_key: SecretStr = SecretStr("")
    cors_origins: list[str] = ["http://127.0.0.1:5173", "http://localhost:5173"]

    @field_validator(
        "episode_media_dir",
        "character_reference_dir",
        "face_detector_path",
        "face_recognizer_path",
        mode="before",
    )
    @classmethod
    def empty_optional_path(cls, value):
        return None if isinstance(value, str) and not value.strip() else value

    @property
    def database_path(self) -> Path:
        return self.data_dir / "searchy.sqlite3"
