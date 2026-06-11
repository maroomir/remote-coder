from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Callable
from pathlib import Path
from threading import Lock

from app.models import UiLanguage
from app.telegram.conversation.context import truncate_snippet
from app.telegram.conversation.models import ConversationEntry
from app.telegram.conversation.protocols import ConversationEntryReader
from app.telegram.conversation.sqlite_rows import row_to_entry
from app.telegram.i18n import instruction_frame_labels


_REPLY_CHAIN_MAX_DEPTH = 32


class ConversationReplyChainResolver:
    def __init__(
        self,
        entry_reader: ConversationEntryReader,
        max_depth: int = _REPLY_CHAIN_MAX_DEPTH,
    ) -> None:
        self._entry_reader = entry_reader
        self._max_depth = max_depth

    def collect_message_ids(
        self, project: str, chat_id: int, reply_to_message_id: int
    ) -> set[int]:
        return {
            entry.message_id
            for entry in self.entries_newest_first(project, chat_id, reply_to_message_id)
            if entry.message_id is not None
        }

    def entries_newest_first(
        self, project: str, chat_id: int, reply_to_message_id: int
    ) -> list[ConversationEntry]:
        chain: list[ConversationEntry] = []
        cur: int | None = reply_to_message_id
        depth = 0
        seen: set[int] = set()
        while cur is not None and depth < self._max_depth:
            if cur in seen:
                break
            seen.add(cur)
            entry = self._entry_reader.get_user_entry_by_message_id(project, chat_id, cur)
            if entry is None:
                break
            chain.append(entry)
            cur = entry.reply_to_message_id
            depth += 1
        return chain


class ConversationSessionResolver:
    def __init__(
        self,
        db_path: Path,
        lock: Lock,
        entry_reader: ConversationEntryReader,
        reply_chain_resolver: ConversationReplyChainResolver,
    ) -> None:
        self._db_path = db_path
        self._lock = lock
        self._entry_reader = entry_reader
        self._reply_chain_resolver = reply_chain_resolver

    def _user_message_id_for_job(self, project: str, chat_id: int, job_id: str) -> int | None:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                row = conn.execute(
                    """
                    SELECT message_id
                    FROM conversation_entries
                    WHERE project = ? AND chat_id = ? AND role = 'user' AND job_id = ?
                    AND message_id IS NOT NULL
                    ORDER BY id ASC
                    LIMIT 1
                    """,
                    (project, chat_id, job_id),
                ).fetchone()
            finally:
                conn.close()
        return int(row[0]) if row is not None and row[0] is not None else None

    def _resolve_root_user_message_id(
        self,
        project: str,
        chat_id: int,
        message_id: int,
        reply_to_message_id: int | None,
    ) -> int:
        if reply_to_message_id is None:
            return message_id
        replied = self._entry_reader.get_entry_by_message_id(
            project, chat_id, reply_to_message_id
        )
        start_user_mid: int | None = None
        if replied is not None and replied.role == "user":
            start_user_mid = replied.message_id
        elif replied is not None and replied.job_id:
            start_user_mid = self._user_message_id_for_job(project, chat_id, replied.job_id)
        if start_user_mid is None:
            return message_id
        chain = self._reply_chain_resolver.entries_newest_first(
            project, chat_id, start_user_mid
        )
        if chain:
            root = chain[-1].message_id
            if root is not None:
                return root
        return start_user_mid

    def resolve_or_create_session(
        self,
        project: str,
        chat_id: int,
        message_id: int,
        reply_to_message_id: int | None = None,
    ) -> str:
        root_mid = self._resolve_root_user_message_id(
            project, chat_id, message_id, reply_to_message_id
        )
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                row = conn.execute(
                    """
                    SELECT session_id FROM agent_sessions
                    WHERE project = ? AND chat_id = ? AND root_message_id = ?
                    """,
                    (project, chat_id, root_mid),
                ).fetchone()
                if row is not None:
                    return str(row[0])
                # Canonical UUID form so it can be passed directly to Claude `--session-id`.
                session_id = str(uuid.uuid4())
                conn.execute(
                    """
                    INSERT INTO agent_sessions (project, chat_id, root_message_id, session_id)
                    VALUES (?, ?, ?, ?)
                    """,
                    (project, chat_id, root_mid, session_id),
                )
                conn.commit()
            finally:
                conn.close()
        return session_id


class ConversationContextFormatter:
    def __init__(
        self,
        db_path: Path,
        lock: Lock,
        entry_reader: ConversationEntryReader,
        reply_chain_resolver: ConversationReplyChainResolver,
        snippet_limit_provider: Callable[[], int],
        latest_job_result_provider: Callable[[str, int, int], str | None],
    ) -> None:
        self._db_path = db_path
        self._lock = lock
        self._entry_reader = entry_reader
        self._reply_chain_resolver = reply_chain_resolver
        self._snippet_limit_provider = snippet_limit_provider
        self._latest_job_result_provider = latest_job_result_provider

    def format_job_context(
        self,
        project: str,
        chat_id: int,
        job_id: str,
        language: UiLanguage = UiLanguage.ENGLISH,
    ) -> str:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                user_row = conn.execute(
                    """
                    SELECT id, project, chat_id, role, text, job_id, message_id, reply_to_message_id
                    FROM conversation_entries
                    WHERE project = ? AND chat_id = ? AND role = 'user' AND job_id = ?
                    ORDER BY id ASC
                    LIMIT 1
                    """,
                    (project, chat_id, job_id),
                ).fetchone()
                result_row = conn.execute(
                    """
                    SELECT text
                    FROM conversation_entries
                    WHERE project = ? AND chat_id = ? AND role = 'job_result' AND job_id = ?
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (project, chat_id, job_id),
                ).fetchone()
                history_rows = conn.execute(
                    """
                    SELECT id, project, chat_id, role, text, job_id, message_id, reply_to_message_id
                    FROM conversation_entries
                    WHERE project = ? AND chat_id = ? AND job_id = ?
                    ORDER BY id ASC
                    LIMIT 20
                    """,
                    (project, chat_id, job_id),
                ).fetchall()
            finally:
                conn.close()

        if user_row is None and result_row is None and not history_rows:
            return ""

        snippet_limit = self._snippet_limit_provider()
        labels = instruction_frame_labels(language)
        lines = [labels.reply_job_open, f"job_id={job_id}:"]
        if user_row is not None:
            user_entry = row_to_entry(user_row)
            if user_entry.message_id is not None:
                lines.append(f"  original_message_id: {user_entry.message_id}")
            lines.append(f"  original_user: {truncate_snippet(user_entry.text, snippet_limit)}")
        else:
            lines.append(f"  original_user: {labels.none_absent}")
        if result_row is not None:
            lines.append(f"  job_result: {truncate_snippet(str(result_row[0]), snippet_limit)}")
        else:
            lines.append(f"  job_result: {labels.none_absent}")
        if history_rows:
            lines.append("  job_history:")
            for row in history_rows:
                entry = row_to_entry(row)
                message_part = (
                    f" message_id={entry.message_id}" if entry.message_id is not None else ""
                )
                lines.append(
                    f"    - {entry.role}{message_part}: {truncate_snippet(entry.text, snippet_limit)}"
                )
        lines.append(labels.reply_job_close)
        return "\n".join(lines)

    def format_reply_context(
        self,
        project: str,
        chat_id: int,
        reply_to_message_id: int,
        language: UiLanguage = UiLanguage.ENGLISH,
    ) -> str:
        reply_entry = self._entry_reader.get_entry_by_message_id(
            project, chat_id, reply_to_message_id
        )
        if reply_entry is not None and reply_entry.role != "user" and reply_entry.job_id:
            return self.format_job_context(project, chat_id, reply_entry.job_id, language)
        return self.format_reply_chain_context(project, chat_id, reply_to_message_id, language)

    def format_reply_chain_context(
        self,
        project: str,
        chat_id: int,
        reply_to_message_id: int,
        language: UiLanguage = UiLanguage.ENGLISH,
    ) -> str:
        newest_first = self._reply_chain_resolver.entries_newest_first(
            project, chat_id, reply_to_message_id
        )
        if not newest_first:
            return ""
        snippet_limit = self._snippet_limit_provider()
        labels = instruction_frame_labels(language)
        ordered = list(reversed(newest_first))
        lines: list[str] = [labels.reply_chain_open]
        for entry in ordered:
            message_id = entry.message_id
            lines.append(f"message_id={message_id}:")
            lines.append(f"  user: {truncate_snippet(entry.text, snippet_limit)}")
            job_text = (
                self._latest_job_result_provider(project, chat_id, message_id)
                if message_id
                else None
            )
            if job_text:
                lines.append(f"  job_result: {truncate_snippet(job_text, snippet_limit)}")
            else:
                lines.append(f"  job_result: {labels.none_absent}")
        lines.append(labels.reply_chain_close)
        return "\n".join(lines)


__all__ = [
    "ConversationContextFormatter",
    "ConversationReplyChainResolver",
    "ConversationSessionResolver",
]
