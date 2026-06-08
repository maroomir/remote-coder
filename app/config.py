import os
from functools import lru_cache
from pathlib import Path
from typing import Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.models import CodexSandboxMode, ModelName


def remote_coder_home() -> Path:
    """Stable per-user config/state home so the CLI works from any directory.

    Overridable with REMOTE_CODER_HOME; defaults to ~/.remote-coder. Holds the
    project registry, state files, worktrees, and the optional global `.env` seed.
    """
    raw = os.environ.get("REMOTE_CODER_HOME", "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".remote-coder"


def worktrees_root() -> Path:
    return (remote_coder_home() / "worktrees").resolve()


def default_worktree_base_dir(project_name: str) -> Path:
    return (worktrees_root() / project_name).resolve()


def resolve_state_path(filename: str, legacy_project_root: Path) -> Path:
    new_path = (remote_coder_home() / filename).resolve()
    if new_path.exists():
        return new_path
    legacy = (legacy_project_root / ".remote-coder" / filename).resolve()
    if legacy.exists():
        return legacy
    return new_path


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    telegram_bot_token: SecretStr | None = Field(
        default=None,
        description=(
            "Optional seed only: written into projects.json when the registry file is missing "
            "or lists no projects. Runtime bots use per-project bot_token in the registry."
        ),
    )
    telegram_allowed_chat_ids: list[int] = Field(
        default_factory=list,
        description="Optional seed only: initial allowed_chat_ids for the seeded default_project record.",
    )
    telegram_allowed_user_ids: list[int] = Field(
        default_factory=list,
        description="Optional seed only: initial allowed_user_ids for the seeded default_project record.",
    )
    telegram_webhook_secret: SecretStr | None = Field(
        default=None,
        description="Optional seed only: initial webhook_secret for the seeded default_project record.",
    )
    telegram_webhook_public_base_url: str | None = Field(
        default=None,
        description=(
            "Runtime public HTTPS base URL used to refresh per-project Telegram webhooks "
            "after project create/update in the admin UI."
        ),
    )

    default_model: ModelName = ModelName.CLAUDE
    default_project: str = "remote-coder"
    project_root: Path = Field(default_factory=remote_coder_home)
    job_timeout_seconds: int = 1800
    keep_worktree_on_success: bool = True
    projects_config_path: Path | None = None
    git_remote_name: str = "origin"

    # 프로젝트+채팅별 대화 기억(SQLite). 미설정 시 ~/.remote-coder/conversations.sqlite3
    # (기존 PROJECT_ROOT/.remote-coder/conversations.sqlite3 가 있으면 하위호환 폴백)
    conversation_db_path: Path | None = None
    # 작업 메타데이터(SQLite). 미설정 시 ~/.remote-coder/jobs.sqlite3
    # (기존 PROJECT_ROOT/.remote-coder/jobs.sqlite3 가 있으면 하위호환 폴백)
    job_db_path: Path | None = None
    conversation_recent_limit: int = 10

    # Codex `codex exec` 샌드박스. 기본 workspace-write (워크트리 내 파일 수정 허용). read-only는 편집 불가.
    codex_sandbox: CodexSandboxMode = CodexSandboxMode.WORKSPACE_WRITE

    @model_validator(mode="after")
    def _normalize_telegram_seed_fields(self) -> Self:
        if self.telegram_bot_token is not None:
            if not self.telegram_bot_token.get_secret_value().strip():
                self.telegram_bot_token = None
        if self.telegram_webhook_secret is not None:
            if not self.telegram_webhook_secret.get_secret_value().strip():
                self.telegram_webhook_secret = None
        if self.telegram_webhook_public_base_url is not None:
            base = self.telegram_webhook_public_base_url.strip().rstrip("/")
            self.telegram_webhook_public_base_url = base or None
        return self

    @model_validator(mode="after")
    def _default_conversation_db_path(self) -> Self:
        if self.conversation_db_path is None:
            self.conversation_db_path = resolve_state_path("conversations.sqlite3", self.project_root)
        return self

    @model_validator(mode="after")
    def _default_job_db_path(self) -> Self:
        if self.job_db_path is None:
            self.job_db_path = resolve_state_path("jobs.sqlite3", self.project_root)
        return self

    @field_validator("telegram_allowed_chat_ids", mode="before")
    @classmethod
    def parse_allowed_chat_ids(cls, value: object) -> list[int]:
        if value in (None, ""):
            return []
        if isinstance(value, list):
            return [int(v) for v in value]
        if isinstance(value, (int, float)):
            return [int(value)]
        if isinstance(value, str):
            parsed = [item.strip() for item in value.split(",") if item.strip()]
            return [int(v) for v in parsed]
        raise ValueError("TELEGRAM_ALLOWED_CHAT_IDS must be list, int, or comma-separated string")

    @field_validator("telegram_allowed_user_ids", mode="before")
    @classmethod
    def parse_allowed_user_ids(cls, value: object) -> list[int]:
        if value in (None, ""):
            return []
        if isinstance(value, list):
            return [int(v) for v in value]
        if isinstance(value, (int, float)):
            return [int(value)]
        if isinstance(value, str):
            parsed = [item.strip() for item in value.split(",") if item.strip()]
            return [int(v) for v in parsed]
        raise ValueError("TELEGRAM_ALLOWED_USER_IDS must be list, int, or comma-separated string")


@lru_cache
def get_settings() -> Settings:
    home = remote_coder_home()
    # cwd ".env" overrides the global home file so in-repo development keeps working.
    return Settings(_env_file=(home / ".env", Path(".env")))
