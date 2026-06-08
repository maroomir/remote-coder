import os
from functools import lru_cache
from pathlib import Path
from typing import Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def remote_coder_home() -> Path:
    """Stable per-user config/state home so the CLI works from any directory.

    Overridable with REMOTE_CODER_HOME; defaults to ~/.remote-coder. Holds the
    project registry, state files, and worktrees.
    """
    raw = os.environ.get("REMOTE_CODER_HOME", "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".remote-coder"


def worktrees_root() -> Path:
    return (remote_coder_home() / "worktrees").resolve()


def default_worktree_base_dir(project_name: str) -> Path:
    return (worktrees_root() / project_name).resolve()


def resolve_state_path(filename: str) -> Path:
    home = remote_coder_home()
    new_path = (home / filename).resolve()
    if new_path.exists():
        return new_path
    legacy = (home / ".remote-coder" / filename).resolve()
    if legacy.exists():
        return legacy
    return new_path


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    telegram_webhook_public_base_url: str | None = Field(
        default=None,
        description=(
            "Runtime public HTTPS base URL used to refresh per-project Telegram webhooks "
            "after project create/update in the admin UI."
        ),
    )
    projects_config_path: Path | None = None
    conversation_db_path: Path | None = None
    job_db_path: Path | None = None

    @model_validator(mode="after")
    def _normalize_webhook_public_base_url(self) -> Self:
        if self.telegram_webhook_public_base_url is not None:
            base = self.telegram_webhook_public_base_url.strip().rstrip("/")
            self.telegram_webhook_public_base_url = base or None
        return self

    @model_validator(mode="after")
    def _default_conversation_db_path(self) -> Self:
        if self.conversation_db_path is None:
            self.conversation_db_path = resolve_state_path("conversations.sqlite3")
        return self

    @model_validator(mode="after")
    def _default_job_db_path(self) -> Self:
        if self.job_db_path is None:
            self.job_db_path = resolve_state_path("jobs.sqlite3")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
