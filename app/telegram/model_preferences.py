from __future__ import annotations

from threading import Lock

from app.models import ModelName


class InMemoryModelPreferenceStore:
    def __init__(self, default_model: ModelName) -> None:
        self._default_model = default_model
        self._values: dict[tuple[str | None, int], ModelName] = {}
        self._lock = Lock()

    def get(self, project_name: str | None, chat_id: int) -> ModelName:
        with self._lock:
            return self._values.get((project_name, chat_id), self._default_model)

    def get_explicit(self, project_name: str | None, chat_id: int) -> ModelName | None:
        with self._lock:
            return self._values.get((project_name, chat_id))

    def set(self, project_name: str | None, chat_id: int, model: ModelName) -> None:
        with self._lock:
            self._values[(project_name, chat_id)] = model

    def clear(self, project_name: str | None, chat_id: int) -> None:
        with self._lock:
            self._values.pop((project_name, chat_id), None)
