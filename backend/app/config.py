"""Application configuration using Pydantic settings."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict

# Look for .env in both backend/ and project root
_env_file = Path(__file__).resolve().parent.parent / ".env"
if not _env_file.exists():
    _env_file = Path(__file__).resolve().parent.parent.parent / ".env"


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=str(_env_file) if _env_file.exists() else ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # AI Model Keys
    anthropic_api_key: str = ""
    gemini_api_key: str = ""

    # AI Model Names (configurable)
    claude_model: str = "claude-opus-4-20250514"
    claude_max_tokens: int = 16000
    gemini_model: str = "gemini-2.5-flash"
    gemini_max_tokens: int = 8192

    # GitHub
    github_token: str = ""
    github_owner: str = ""

    # Database
    database_url: str = "postgresql+asyncpg://postgres:admin@localhost:5432/ai_engineer"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Application
    human_in_the_loop: bool = True
    max_retries: int = 3
    sandbox_timeout: int = 300
    log_level: str = "INFO"

    # Security
    secret_key: str = "change-this-to-a-random-secret-key"
    allowed_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # Paths
    projects_dir: str = "/projects"

    @property
    def cors_origins(self) -> List[str]:
        """Parse allowed origins into a list."""
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def sync_database_url(self) -> str:
        """Return synchronous database URL for Celery workers."""
        return self.database_url.replace("+asyncpg", "+psycopg2").replace(
            "postgresql+psycopg2", "postgresql"
        )


@lru_cache()
def get_settings() -> Settings:
    """Return cached settings instance."""
    return Settings()
