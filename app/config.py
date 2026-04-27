from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.models import ModelName


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    telegram_bot_token: SecretStr
    telegram_allowed_chat_ids: list[int]
    telegram_webhook_secret: SecretStr | None = None

    default_model: ModelName = ModelName.CLAUDE
    default_project: str = "remote-coder"
    project_root: Path
    worktree_base_dir: Path
    job_timeout_seconds: int = 1800
    keep_worktree_on_success: bool = True
    projects_config_path: Path | None = None

    @field_validator("telegram_allowed_chat_ids", mode="before")
    @classmethod
    def parse_allowed_chat_ids(cls, value: object) -> list[int]:
        if isinstance(value, list):
            return [int(v) for v in value]
        if isinstance(value, (int, float)):
            return [int(value)]
        if isinstance(value, str):
            parsed = [item.strip() for item in value.split(",") if item.strip()]
            return [int(v) for v in parsed]
        raise ValueError("TELEGRAM_ALLOWED_CHAT_IDS must be list, int, or comma-separated string")


@lru_cache
def get_settings() -> Settings:
    return Settings()
