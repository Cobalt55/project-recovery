"""Typed environment configuration for Project Recovery."""

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ModelId = Literal["gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol"]
ReasoningEffort = Literal["low", "medium", "high"]

ALLOWED_MODELS: tuple[ModelId, ...] = (
    "gpt-5.6-luna",
    "gpt-5.6-terra",
    "gpt-5.6-sol",
)
ALLOWED_REASONING_EFFORTS: tuple[ReasoningEffort, ...] = ("low", "medium", "high")


class Settings(BaseSettings):
    """Application settings loaded from environment variables or a local env file.

    Secret values are required so production cannot silently start with an unsafe
    fallback. ``SecretStr`` keeps their values out of normal representations.
    Environment names are case-insensitive and whitespace around string values is
    normalized by pydantic-settings.
    """

    model_config = SettingsConfigDict(
        case_sensitive=False,
        env_file=(".env", ".env.local"),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
        str_strip_whitespace=True,
    )

    openai_api_key: SecretStr
    openai_vector_store_id: str
    database_url: SecretStr
    app_session_secret: SecretStr
    chainlit_auth_secret: SecretStr

    app_name: str = "Project Recovery"
    environment: str = "development"
    default_model: ModelId = "gpt-5.6-terra"
    default_reasoning_effort: ReasoningEffort = "medium"
    tracing_enabled: bool = True
    trace_include_sensitive_data: bool = False
    attachment_storage_path: str = "uploads"
    trusted_hosts: tuple[str, ...] = ("localhost", "127.0.0.1", "testserver")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide validated settings instance."""

    return Settings()


__all__ = [
    "ALLOWED_MODELS",
    "ALLOWED_REASONING_EFFORTS",
    "ModelId",
    "ReasoningEffort",
    "Settings",
    "get_settings",
]
