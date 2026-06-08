from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from typing import Self

from pydantic import BaseModel, model_validator

from app.config import resolve_state_path
from app.models import UiLanguage


class AdvancedSettings(BaseModel):
    model_config = {"extra": "forbid"}

    ui_language: UiLanguage = UiLanguage.ENGLISH
    server_lifecycle_notify_enabled: bool = True
    pull_projects_on_server_startup_enabled: bool = False
    auto_merge_to_main_enabled: bool = False
    delete_rebased_branch_enabled: bool = True
    natural_job_confirmation_buttons_enabled: bool = False
    conversation_memory_limit_enabled: bool = False
    conversation_memory_max_rows: int | None = None
    conversation_memory_max_bytes: int | None = None
    status_recent_job_limit: int = 10
    job_timeout_seconds: int | None = None

    @model_validator(mode="after")
    def _validate_memory_limits(self) -> Self:
        if self.conversation_memory_limit_enabled:
            has_rows = self.conversation_memory_max_rows is not None and self.conversation_memory_max_rows > 0
            has_bytes = (
                self.conversation_memory_max_bytes is not None and self.conversation_memory_max_bytes > 0
            )
            if not has_rows and not has_bytes:
                raise ValueError(
                    "When conversation_memory_limit_enabled is set, at least one of "
                    "conversation_memory_max_rows or conversation_memory_max_bytes must be a positive value.",
                )
        if self.conversation_memory_max_rows is not None and self.conversation_memory_max_rows <= 0:
            raise ValueError("conversation_memory_max_rows must be positive or blank.")
        if self.conversation_memory_max_bytes is not None and self.conversation_memory_max_bytes <= 0:
            raise ValueError("conversation_memory_max_bytes must be positive or blank.")
        if self.status_recent_job_limit < 1:
            raise ValueError("status_recent_job_limit must be at least 1.")
        if self.job_timeout_seconds is not None and self.job_timeout_seconds <= 0:
            raise ValueError("job_timeout_seconds must be positive or blank.")
        return self


def advanced_settings_path_for_project_root(project_root: Path) -> Path:
    return resolve_state_path("advanced_settings.json", project_root.expanduser())


class FileAdvancedSettingsStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = Lock()
        self._cached = AdvancedSettings()

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> AdvancedSettings:
        with self._lock:
            if not self._path.exists():
                self._cached = AdvancedSettings()
                return self._cached.model_copy(deep=True)
            raw = self._path.read_text(encoding="utf-8")
            data = json.loads(raw) if raw.strip() else {}
            if isinstance(data, dict):
                data.pop("auto_pull_on_project_switch", None)
            self._cached = AdvancedSettings.model_validate(data)
            return self._cached.model_copy(deep=True)

    def get(self) -> AdvancedSettings:
        with self._lock:
            return self._cached.model_copy(deep=True)

    def save(self, settings: AdvancedSettings) -> AdvancedSettings:
        validated = AdvancedSettings.model_validate(settings.model_dump(mode="json"))
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            text = json.dumps(validated.model_dump(mode="json"), indent=2, ensure_ascii=False)
            self._path.write_text(text + "\n", encoding="utf-8")
            self._cached = validated
            return self._cached.model_copy(deep=True)
