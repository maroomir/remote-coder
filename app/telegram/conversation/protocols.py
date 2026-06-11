from __future__ import annotations

from typing import Protocol

from app.models import UiLanguage
from app.telegram.conversation.models import ConversationEntry


class ConversationEntryReader(Protocol):
    def get_entry_by_message_id(
        self, project: str, chat_id: int, message_id: int
    ) -> ConversationEntry | None: ...

    def get_user_entry_by_message_id(
        self, project: str, chat_id: int, message_id: int
    ) -> ConversationEntry | None: ...


class ConversationContextStore(ConversationEntryReader, Protocol):
    def snippet_max_chars(self) -> int: ...

    def get_bound_branch(self, project: str, chat_id: int, message_id: int) -> str | None: ...

    def format_job_context(
        self,
        project: str,
        chat_id: int,
        job_id: str,
        language: UiLanguage = UiLanguage.ENGLISH,
    ) -> str: ...

    def format_reply_context(
        self,
        project: str,
        chat_id: int,
        reply_to_message_id: int,
        language: UiLanguage = UiLanguage.ENGLISH,
    ) -> str: ...

    def collect_reply_chain_message_ids(
        self, project: str, chat_id: int, reply_to_message_id: int
    ) -> set[int]: ...

    def list_recent(
        self, project: str, chat_id: int, limit: int
    ) -> list[ConversationEntry]: ...


__all__ = [
    "ConversationContextStore",
    "ConversationEntryReader",
]
