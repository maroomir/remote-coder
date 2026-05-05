from __future__ import annotations

from threading import Lock


class InMemoryProjectPreferenceStore:
    def __init__(self) -> None:
        self._values: dict[int, str] = {}
        self._lock = Lock()

    def get(self, chat_id: int) -> str | None:
        with self._lock:
            return self._values.get(chat_id)

    def set(self, chat_id: int, project_name: str) -> None:
        with self._lock:
            self._values[chat_id] = project_name

    def clear(self, chat_id: int) -> None:
        # 선택을 제거하면 적용 프로젝트는 레지스트리 기본값으로 폴백합니다.
        with self._lock:
            self._values.pop(chat_id, None)
