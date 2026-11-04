from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    
    model_config = SettingsConfigDict(
        env_file=(".env", str(Path(__file__).resolve().parents[3] / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # 1. Storage & Data Paths (loaded from .env)
    data_dir: Path = Field(default=Path("var"))
    database_path: Path | None = Field(default=None)
    collection_id: str = Field(default="friends", max_length=80)
    import_root: Path = Field(default=Path("data/episodes_splitted"))
    episode_media_dir: Path | None = Field(default=None)
    character_reference_dir: Path | None = Field(default=None)
    model_cache_dir: Path = Field(default=Path(".cache/models"))

    # Local Face Models & Thresholds (loaded from .env)
    face_detector_path: Path | None = Field(default=None)
    face_recognizer_path: Path | None = Field(default=None)
    face_match_threshold: float = Field(default=0.5, ge=0, le=1)
    face_match_margin: float = Field(default=0.08, ge=0, le=1)

    # 2. Database Configuration (loaded from .env)
    neo4j_uri: str = Field(default="bolt://localhost:7687")
    neo4j_user: str = Field(default="neo4j")
    neo4j_password: SecretStr = SecretStr("")
    neo4j_database: str = Field(default="neo4j")

    qdrant_url: str = Field(default="http://localhost:6333")
    qdrant_api_key: SecretStr = SecretStr("")
    qdrant_collection_name: str = Field(default="searchy_scenes")
    qdrant_episode_collection_name: str = Field(default="searchy_episodes")

    # 3. LLM Configuration (loaded from .env)
    llm_provider: Literal["GOOGLE_GENAI", "GROQ", "NVIDIA_NIM", ""] = Field(default="")
    llm_model_id: str = Field(default="")

    # API Keys & Endpoints (loaded from .env)
    gemini_api_key: SecretStr = SecretStr("")
    groq_api_key: SecretStr = SecretStr("")
    nvidia_nim_api_key: SecretStr = SecretStr("")
    nvidia_nim_base_url: str = Field(default="")
    nvidia_nim_model: str = Field(default="")
    hf_token: SecretStr = SecretStr("")
    hf_hub_enable_hf_transfer: bool = Field(default=False)
    api_key: SecretStr = SecretStr("")

    # 4. Embedding Configuration (loaded from .env)
    embedding_provider: Literal["LOCAL_EMBEDDING", ""] = Field(default="LOCAL_EMBEDDING")
    embedding_model_id: str = Field(default="")
    embedding_device: str = Field(default="cpu")
    embedding_batch_size: int = Field(default=16, ge=1, le=256)

    # 5. Visual Search & Audio Transcription (loaded from .env)
    visual_enabled: bool = Field(default=False)
    visual_model_id: str = Field(default="")
    whisper_model_id: str = Field(default="")
    whisper_device: str = Field(default="cpu")
    whisper_compute_type: str = Field(default="int8")

    # 6. Video Processing & FFmpeg (loaded from .env)
    ffmpeg_path: str = Field(default="ffmpeg")
    ffprobe_path: str = Field(default="ffprobe")
    max_upload_mb: int = Field(default=2048, ge=1)
    max_video_seconds: int = Field(default=14400, ge=1)
    frames_per_scene: int = Field(default=3, ge=1, le=8)
    provider_timeout_seconds: float = Field(default=90, gt=0)

    # 7. Captioning & VLM Configuration (loaded from .env)
    caption_backend: Literal["api", "local", ""] = Field(default="api")
    caption_provider: Literal["GOOGLE_GENAI", "GROQ", ""] = Field(default="")
    caption_api_model_id: str = Field(default="")
    caption_model_id: str = Field(default="")
    vllm_base_url: str = Field(default="")
    vlm_identity_min_confidence: float = Field(default=0.85, ge=0, le=1)
    vlm_max_images: int | None = Field(default=None, ge=1, le=32)

    # 8. Chat Assistant Configuration (loaded from .env)
    chat_model: str = Field(default="")
    chat_context: int = Field(default=8192, ge=1024)
    chat_max_tokens: int = Field(default=1500, ge=64)
    chat_temperature: float = Field(default=0.2, ge=0, le=2)
    chat_source_limit: int = Field(default=20, ge=1, le=40)

    # 9. Search & Worker Thresholds (loaded from .env)
    worker_enabled: bool = Field(default=True)
    worker_poll_seconds: float = Field(default=2, gt=0)
    worker_shutdown_timeout_seconds: float = Field(default=10, gt=0)
    job_lease_seconds: int = Field(default=120, ge=30)
    candidate_limit: int = Field(default=80, ge=10, le=500)
    semantic_min_score: float = Field(default=0.32, ge=-1, le=1)
    visual_min_score: float = Field(default=0.23, ge=-1, le=1)

    # 10. CORS Configuration (loaded from .env)
    cors_origins: list[str] | str = Field(default=["http://127.0.0.1:5173", "http://localhost:5173"])

    @field_validator(
        "episode_media_dir",
        "character_reference_dir",
        "face_detector_path",
        "face_recognizer_path",
        "database_path",
        mode="before",
    )
    @classmethod
    def empty_optional_path(cls, value):
        return None if isinstance(value, str) and not value.strip() else value

    @model_validator(mode="after")
    def _apply_derived_defaults(self) -> "Settings":
        if self.database_path is None:
            self.database_path = self.data_dir / "searchy.sqlite3"
        if isinstance(self.cors_origins, str):
            val = self.cors_origins.strip()
            if val.startswith("[") and val.endswith("]"):
                import json
                try:
                    self.cors_origins = json.loads(val)
                except Exception:
                    self.cors_origins = [o.strip() for o in val.strip("[]").split(",") if o.strip()]
            else:
                self.cors_origins = [o.strip() for o in val.split(",") if o.strip()]
        return self
