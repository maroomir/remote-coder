from functools import lru_cache
from pathlib import Path
from typing import Self

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.models import CodexSandboxMode, ModelName


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    telegram_bot_token: SecretStr
    telegram_allowed_chat_ids: list[int]
    telegram_allowed_user_ids: list[int] = []
    telegram_webhook_secret: SecretStr | None = None

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
    def _default_conversation_db_path(self) -> Self:
        if self.conversation_db_path is None:
            self.conversation_db_path = (self.project_root / ".remote-coder" / "conversations.sqlite3").resolve()
        return self

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
