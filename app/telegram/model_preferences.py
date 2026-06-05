from __future__ import annotations

from dataclasses import dataclass
from threading import Lock

from app.models import ModelName


@dataclass(frozen=True)
class ModelPreference:
    provider: ModelName
    model_id: str | None = None


class InMemoryModelPreferenceStore:
    def __init__(self, default_model: ModelName) -> None:
        self._default_model = default_model
        self._values: dict[tuple[str | None, int], ModelPreference] = {}
        self._lock = Lock()

    def get(self, project_name: str | None, chat_id: int) -> ModelName:
        with self._lock:
            selection = self._values.get((project_name, chat_id))
            return selection.provider if selection is not None else self._default_model

    def get_explicit(self, project_name: str | None, chat_id: int) -> ModelName | None:
        with self._lock:
            selection = self._values.get((project_name, chat_id))
            return selection.provider if selection is not None else None

    def set(self, project_name: str | None, chat_id: int, model: ModelName) -> None:
        self.set_selection(project_name, chat_id, ModelPreference(model))

    def get_selection(self, project_name: str | None, chat_id: int) -> ModelPreference:
        with self._lock:
            return self._values.get(
                (project_name, chat_id),
                ModelPreference(self._default_model),
            )

    def get_explicit_selection(
        self,
        project_name: str | None,
        chat_id: int,
    ) -> ModelPreference | None:
        with self._lock:
            return self._values.get((project_name, chat_id))

    def set_selection(
        self,
        project_name: str | None,
        chat_id: int,
        selection: ModelPreference,
    ) -> None:
        with self._lock:
            self._values[(project_name, chat_id)] = selection

    def clear(self, project_name: str | None, chat_id: int) -> None:
        with self._lock:
            self._values.pop((project_name, chat_id), None)
