from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.jobs.schemas import JobRequest


@dataclass(frozen=True)
class PendingConfirmation:
    command_name: str
    action: str
    job_request: JobRequest | None = None
    original_text: str | None = None


class InMemoryConfirmationStore:
    def __init__(self) -> None:
        self._values: dict[int, PendingConfirmation] = {}
        self._lock = Lock()

    def get(self, chat_id: int) -> PendingConfirmation | None:
        with self._lock:
            return self._values.get(chat_id)

    def set(self, chat_id: int, confirmation: PendingConfirmation) -> None:
        with self._lock:
            self._values[chat_id] = confirmation

    def pop(self, chat_id: int) -> PendingConfirmation | None:
        with self._lock:
            return self._values.pop(chat_id, None)
