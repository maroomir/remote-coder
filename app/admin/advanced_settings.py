from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from typing import Self

from pydantic import BaseModel, model_validator


class AdvancedSettings(BaseModel):
    """전역 고급 설정. 기본값은 모두 비활성(기존 동작 유지)."""

    model_config = {"extra": "forbid"}

    auto_merge_to_main_enabled: bool = False
    conversation_memory_limit_enabled: bool = False
    conversation_memory_max_rows: int | None = None
    conversation_memory_max_bytes: int | None = None

    @model_validator(mode="after")
    def _validate_memory_limits(self) -> Self:
        if self.conversation_memory_limit_enabled:
            has_rows = self.conversation_memory_max_rows is not None and self.conversation_memory_max_rows > 0
            has_bytes = (
                self.conversation_memory_max_bytes is not None and self.conversation_memory_max_bytes > 0
            )
            if not has_rows and not has_bytes:
                raise ValueError(
                    "conversation_memory_limit_enabled일 때는 "
                    "conversation_memory_max_rows 또는 conversation_memory_max_bytes 중 "
                    "하나 이상을 양수로 지정해야 합니다.",
                )
        if self.conversation_memory_max_rows is not None and self.conversation_memory_max_rows <= 0:
            raise ValueError("conversation_memory_max_rows는 양수이거나 비워야 합니다.")
        if self.conversation_memory_max_bytes is not None and self.conversation_memory_max_bytes <= 0:
            raise ValueError("conversation_memory_max_bytes는 양수이거나 비워야 합니다.")
        return self


def advanced_settings_path_for_project_root(project_root: Path) -> Path:
    return (project_root.expanduser().resolve() / ".remote-coder" / "advanced_settings.json").resolve()


class FileAdvancedSettingsStore:
    """고급 설정을 JSON 파일로 읽고 씁니다."""

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
