from functools import lru_cache
from pathlib import Path
from typing import Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.models import CodexSandboxMode, ModelName


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
    project_root: Path
    worktree_base_dir: Path
    job_timeout_seconds: int = 1800
    keep_worktree_on_success: bool = True
    projects_config_path: Path | None = None
    git_remote_name: str = "origin"

    # 프로젝트+채팅별 대화 기억(SQLite). 미설정 시 PROJECT_ROOT/.remote-coder/conversations.sqlite3
    conversation_db_path: Path | None = None
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
            self.conversation_db_path = (self.project_root / ".remote-coder" / "conversations.sqlite3").resolve()
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
    return Settings()
