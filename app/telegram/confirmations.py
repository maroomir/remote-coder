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
    target_job_id: str | None = None
    prepared_payload: str | None = None
    reply_to_message_id: int | None = None


class InMemoryConfirmationStore:
    def __init__(self) -> None:
        self._values: dict[tuple[str | None, int], PendingConfirmation] = {}
        self._lock = Lock()

    def get(self, project_name: str | None, chat_id: int) -> PendingConfirmation | None:
        with self._lock:
            return self._values.get((project_name, chat_id))

    def set(self, project_name: str | None, chat_id: int, confirmation: PendingConfirmation) -> None:
        with self._lock:
            self._values[(project_name, chat_id)] = confirmation

    def pop(self, project_name: str | None, chat_id: int) -> PendingConfirmation | None:
        with self._lock:
            return self._values.pop((project_name, chat_id), None)
