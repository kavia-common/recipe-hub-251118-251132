"""Application configuration for the Recipe Hub backend."""

from functools import lru_cache
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed application settings."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Recipe Hub API"
    app_description: str = (
        "FastAPI backend for Recipe Hub with authentication, recipe management, "
        "favorites, shopping lists, profiles, and moderation workflows."
    )
    app_version: str = "1.0.0"

    database_url: str = Field(
        default="sqlite+pysqlite:///./recipe_hub.db",
        description=(
            "Database connection URL. For full-stack integration, request a real DATABASE_URL "
            "that points to the recipe_db PostgreSQL container from the user/orchestrator."
        ),
        alias="DATABASE_URL",
    )
    jwt_secret_key: str = Field(
        default="development-secret-key",
        description="JWT signing key. Request a secure value from the user/orchestrator.",
        alias="JWT_SECRET_KEY",
    )
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    jwt_expire_minutes: int = Field(default=120, alias="JWT_EXPIRE_MINUTES")
    cors_origins: List[str] = Field(default=["*"], alias="CORS_ORIGINS")
    default_admin_email: str = Field(default="admin@recipehub.dev", alias="DEFAULT_ADMIN_EMAIL")
    default_admin_password: str = Field(default="ChangeMe123!", alias="DEFAULT_ADMIN_PASSWORD")

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_cors_origins(cls, value: object) -> List[str]:
        """Normalize CORS origins from env strings or arrays."""
        if isinstance(value, str):
            cleaned = [item.strip() for item in value.split(",") if item.strip()]
            return cleaned or ["*"]
        if isinstance(value, list):
            return value or ["*"]
        return ["*"]


@lru_cache
# PUBLIC_INTERFACE
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()
