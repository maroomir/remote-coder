from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ConversationEntry:
    id: int
    project: str
    chat_id: int
    role: str
    text: str
    job_id: str | None
    message_id: int | None = None
    reply_to_message_id: int | None = None


@dataclass(frozen=True)
class ConversationRoleCount:
    role: str
    count: int


@dataclass(frozen=True)
class ConversationDbChatStats:
    db_path: Path
    db_exists: bool
    db_size_bytes: int
    total_rows: int
    rows_by_role: dict[str, int]
    session_count: int = 0


@dataclass(frozen=True)
class ConversationReport:
    project: str
    chat_id: int
    total_entries: int
    role_counts: list[ConversationRoleCount]
    latest_user_text: str | None
    latest_job_id: str | None
    latest_job_result: str | None
    recent_entries: list[ConversationEntry]

    def count_for(self, role: str) -> int:
        for item in self.role_counts:
            if item.role == role:
                return item.count
        return 0


__all__ = [
    "ConversationDbChatStats",
    "ConversationEntry",
    "ConversationReport",
    "ConversationRoleCount",
]
