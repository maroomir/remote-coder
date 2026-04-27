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
