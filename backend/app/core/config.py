"""
Application configuration using Pydantic Settings.
All environment variables are centralized here.
"""
from pydantic_settings import BaseSettings
from pydantic import field_validator
from functools import lru_cache
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    # MongoDB
    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_database: str = "ai_teacher"

    # Ollama
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "gemma4:31b-cloud"
    ollama_timeout: int = 120

    # Embedding
    embedding_model: str = "gemma4:31b-cloud"
    embedding_dim: int = 0

    # App
    secret_key: str = "dev-secret-key"
    debug: bool = True
    upload_dir: str = str(APP_DIR / "static" / "uploads")
    max_upload_size_mb: int = 50

    # TTS (optional)
    tts_provider: str = ""
    tts_api_key: str = ""
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = "pMsXgVXv3BLzUgSXRplE"
    elevenlabs_model_id: str = "eleven_turbo_v2"
    edge_tts_voice: str = "en-IN-NeerjaNeural"

    # Avatar (optional)
    avatar_provider: str = ""
    avatar_api_key: str = ""
    simli_api_key: str = ""
    simli_face_id: str = "cace3ef7-a4c4-425d-a8cf-a5358eb0c427"

    class Config:
        env_file = str(PROJECT_ROOT / ".env")
        env_file_encoding = "utf-8"
        extra = "ignore"

    @field_validator("ollama_base_url")
    @classmethod
    def strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/")

    @field_validator("debug", mode="before")
    @classmethod
    def parse_debug_mode(cls, v) -> bool:
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            normalized = v.strip().lower()
            if normalized in {"release", "prod", "production", "false", "0", "no", "off"}:
                return False
            if normalized in {"debug", "dev", "development", "true", "1", "yes", "on"}:
                return True
        return v


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
