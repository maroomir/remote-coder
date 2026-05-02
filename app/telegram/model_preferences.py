from __future__ import annotations

from threading import Lock

from app.models import ModelName


class InMemoryModelPreferenceStore:
    def __init__(self, default_model: ModelName) -> None:
        self._default_model = default_model
        self._values: dict[int, ModelName] = {}
        self._lock = Lock()

    def get(self, chat_id: int) -> ModelName:
        with self._lock:
            return self._values.get(chat_id, self._default_model)

    def set(self, chat_id: int, model: ModelName) -> None:
        with self._lock:
            self._values[chat_id] = model

    def clear(self, chat_id: int) -> None:
        """채팅별 `/model` 선택을 제거하면 서버 기본 모델로 폴백합니다."""
        with self._lock:
            self._values.pop(chat_id, None)
