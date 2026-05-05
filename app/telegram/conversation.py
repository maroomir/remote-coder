from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from app.admin.advanced_settings import FileAdvancedSettingsStore


_AMBIGUOUS_FOLLOWUP = re.compile(
    r"^\s*(작업\s*시작해줘|진행해줘|그거\s*해줘|시작해줘)\s*$",
    re.UNICODE | re.IGNORECASE,
)

_REPLY_SNIPPET_MAX = 800
# 순환 reply 체인 방지 상한.
_REPLY_CHAIN_MAX_DEPTH = 32


def is_ambiguous_followup(text: str) -> bool:
    return bool(_AMBIGUOUS_FOLLOWUP.match(text.strip()))


def _truncate_snippet(text: str, limit: int = _REPLY_SNIPPET_MAX) -> str:
    snippet = text.strip().replace("\r\n", "\n").replace("\r", "\n")
    if len(snippet) > limit:
        return snippet[:limit].rstrip() + "...(truncated)"
    return snippet


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


def _ensure_entry_columns(conn: sqlite3.Connection) -> None:
    cur = conn.execute("PRAGMA table_info(conversation_entries)")
    names = {str(row[1]) for row in cur.fetchall()}
    if "message_id" not in names:
        conn.execute("ALTER TABLE conversation_entries ADD COLUMN message_id INTEGER")
    if "reply_to_message_id" not in names:
        conn.execute("ALTER TABLE conversation_entries ADD COLUMN reply_to_message_id INTEGER")


class SQLiteConversationStore:
    def __init__(
        self,
        db_path: Path,
        advanced_settings_store: FileAdvancedSettingsStore | None = None,
    ) -> None:
        self._db_path = db_path.resolve()
        self._lock = Lock()
        self._advanced_settings_store = advanced_settings_store
        self.ensure_schema()

    @property
    def db_path(self) -> Path:
        return self._db_path

    def ensure_schema(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS conversation_entries (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        project TEXT NOT NULL,
                        chat_id INTEGER NOT NULL,
                        role TEXT NOT NULL,
                        text TEXT NOT NULL,
                        job_id TEXT,
                        message_id INTEGER,
                        reply_to_message_id INTEGER,
                        created_at TEXT NOT NULL DEFAULT (datetime('now'))
                    )
                    """
                )
                _ensure_entry_columns(conn)
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_conversation_project_chat_id
                    ON conversation_entries (project, chat_id, id)
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_conversation_user_message_id
                    ON conversation_entries (project, chat_id, message_id)
                    WHERE role = 'user' AND message_id IS NOT NULL
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS message_branch_links (
                        project TEXT NOT NULL,
                        chat_id INTEGER NOT NULL,
                        message_id INTEGER NOT NULL,
                        branch TEXT NOT NULL,
                        job_id TEXT,
                        created_at TEXT NOT NULL DEFAULT (datetime('now')),
                        updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                        PRIMARY KEY (project, chat_id, message_id)
                    )
                    """
                )
                conn.commit()
            finally:
                conn.close()

    def reset(self) -> None:
        with self._lock:
            if self._db_path.exists():
                self._db_path.unlink()
        self.ensure_schema()

    @staticmethod
    def _delete_oldest_entries(conn: sqlite3.Connection, limit: int) -> None:
        if limit <= 0:
            return
        conn.execute(
            """
            DELETE FROM conversation_entries
            WHERE id IN (
                SELECT id FROM conversation_entries ORDER BY id ASC LIMIT ?
            )
            """,
            (limit,),
        )

    @staticmethod
    def _cleanup_orphan_branch_links(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            DELETE FROM message_branch_links
            WHERE message_id IS NOT NULL
            AND message_id NOT IN (
                SELECT message_id FROM conversation_entries
                WHERE message_id IS NOT NULL
            )
            """
        )

    def _apply_memory_limits(self, conn: sqlite3.Connection) -> None:
        if self._advanced_settings_store is None:
            return
        cfg = self._advanced_settings_store.get()
        if not cfg.conversation_memory_limit_enabled:
            return
        max_rows = cfg.conversation_memory_max_rows
        max_bytes = cfg.conversation_memory_max_bytes

        for _ in range(500):
            total = int(conn.execute("SELECT COUNT(*) FROM conversation_entries").fetchone()[0])
            if max_rows is None or total <= max_rows:
                break
            to_delete = total - max_rows
            self._delete_oldest_entries(conn, to_delete)
            self._cleanup_orphan_branch_links(conn)
            conn.commit()

        for _ in range(500):
            if max_bytes is None:
                break
            conn.commit()
            size = self._db_path.stat().st_size if self._db_path.exists() else 0
            if size <= max_bytes:
                break
            total = int(conn.execute("SELECT COUNT(*) FROM conversation_entries").fetchone()[0])
            if total == 0:
                break
            batch = min(100, max(1, total // 5))
            self._delete_oldest_entries(conn, batch)
            self._cleanup_orphan_branch_links(conn)
            conn.commit()
            conn.execute("VACUUM")

    def append(
        self,
        *,
        project: str,
        chat_id: int,
        role: str,
        text: str,
        job_id: str | None = None,
        message_id: int | None = None,
        reply_to_message_id: int | None = None,
    ) -> None:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                conn.execute(
                    """
                    INSERT INTO conversation_entries (
                        project, chat_id, role, text, job_id, message_id, reply_to_message_id
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (project, chat_id, role, text, job_id, message_id, reply_to_message_id),
                )
                conn.commit()
                self._apply_memory_limits(conn)
            finally:
                conn.close()

    def list_recent(self, project: str, chat_id: int, limit: int) -> list[ConversationEntry]:
        if limit <= 0:
            return []
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                cur = conn.execute(
                    """
                    SELECT id, project, chat_id, role, text, job_id, message_id, reply_to_message_id
                    FROM conversation_entries
                    WHERE project = ? AND chat_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (project, chat_id, limit),
                )
                rows = cur.fetchall()
            finally:
                conn.close()
        rows.reverse()
        return [_row_to_entry(r) for r in rows]

    def get_user_entry_by_message_id(
        self, project: str, chat_id: int, message_id: int
    ) -> ConversationEntry | None:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                row = conn.execute(
                    """
                    SELECT id, project, chat_id, role, text, job_id, message_id, reply_to_message_id
                    FROM conversation_entries
                    WHERE project = ? AND chat_id = ? AND role = 'user' AND message_id = ?
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (project, chat_id, message_id),
                ).fetchone()
            finally:
                conn.close()
        return _row_to_entry(row) if row is not None else None

    def get_latest_job_result_text_for_user_message(
        self, project: str, chat_id: int, message_id: int
    ) -> str | None:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                link = conn.execute(
                    """
                    SELECT job_id
                    FROM message_branch_links
                    WHERE project = ? AND chat_id = ? AND message_id = ?
                    """,
                    (project, chat_id, message_id),
                ).fetchone()
                if link is None or link[0] is None:
                    return None
                job_id = str(link[0])
                row = conn.execute(
                    """
                    SELECT text
                    FROM conversation_entries
                    WHERE project = ? AND chat_id = ? AND role = 'job_result' AND job_id = ?
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (project, chat_id, job_id),
                ).fetchone()
            finally:
                conn.close()
        return str(row[0]) if row is not None else None

    def collect_reply_chain_message_ids(
        self, project: str, chat_id: int, reply_to_message_id: int
    ) -> set[int]:
        ids: set[int] = set()
        cur: int | None = reply_to_message_id
        depth = 0
        seen: set[int] = set()
        while cur is not None and depth < _REPLY_CHAIN_MAX_DEPTH:
            if cur in seen:
                break
            seen.add(cur)
            entry = self.get_user_entry_by_message_id(project, chat_id, cur)
            if entry is None or entry.message_id is None:
                break
            ids.add(entry.message_id)
            cur = entry.reply_to_message_id
            depth += 1
        return ids

    def get_reply_chain_user_entries_newest_first(
        self, project: str, chat_id: int, reply_to_message_id: int
    ) -> list[ConversationEntry]:
        chain: list[ConversationEntry] = []
        cur: int | None = reply_to_message_id
        depth = 0
        seen: set[int] = set()
        while cur is not None and depth < _REPLY_CHAIN_MAX_DEPTH:
            if cur in seen:
                break
            seen.add(cur)
            entry = self.get_user_entry_by_message_id(project, chat_id, cur)
            if entry is None:
                break
            chain.append(entry)
            cur = entry.reply_to_message_id
            depth += 1
        return chain

    def format_reply_chain_context(self, project: str, chat_id: int, reply_to_message_id: int) -> str:
        newest_first = self.get_reply_chain_user_entries_newest_first(project, chat_id, reply_to_message_id)
        if not newest_first:
            return ""
        ordered = list(reversed(newest_first))
        lines: list[str] = ["[Reply 체인 맥락]"]
        for e in ordered:
            mid = e.message_id
            lines.append(f"message_id={mid}:")
            lines.append(f"  user: {_truncate_snippet(e.text)}")
            job_text = self.get_latest_job_result_text_for_user_message(project, chat_id, mid) if mid else None
            if job_text:
                lines.append(f"  job_result: {_truncate_snippet(job_text)}")
            else:
                lines.append("  job_result: (없음)")
        lines.append("[/Reply 체인 맥락]")
        return "\n".join(lines)

    def bind_message_branch(
        self,
        *,
        project: str,
        chat_id: int,
        message_id: int,
        branch: str,
        job_id: str | None = None,
    ) -> None:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                conn.execute(
                    """
                    INSERT INTO message_branch_links (project, chat_id, message_id, branch, job_id)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(project, chat_id, message_id)
                    DO UPDATE SET
                        branch = excluded.branch,
                        job_id = excluded.job_id,
                        updated_at = datetime('now')
                    """,
                    (project, chat_id, message_id, branch, job_id),
                )
                conn.commit()
            finally:
                conn.close()

    def get_bound_branch(self, project: str, chat_id: int, message_id: int) -> str | None:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                row = conn.execute(
                    """
                    SELECT branch
                    FROM message_branch_links
                    WHERE project = ? AND chat_id = ? AND message_id = ?
                    """,
                    (project, chat_id, message_id),
                ).fetchone()
            finally:
                conn.close()
        return str(row[0]) if row is not None and row[0] is not None else None

    def get_entries_for_branch(
        self, project: str, chat_id: int, branch: str
    ) -> list[tuple[str, str | None]]:
        # 반환: (user_text, job_result_text or None) 시간순 목록.
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                links = conn.execute(
                    """
                    SELECT message_id, job_id
                    FROM message_branch_links
                    WHERE project = ? AND chat_id = ? AND branch = ?
                    ORDER BY created_at ASC
                    """,
                    (project, chat_id, branch),
                ).fetchall()
            finally:
                conn.close()

        result: list[tuple[str, str | None]] = []
        for message_id, job_id in links:
            user_entry = self.get_user_entry_by_message_id(project, chat_id, message_id)
            if user_entry is None:
                continue
            job_result: str | None = None
            if job_id:
                with self._lock:
                    conn = sqlite3.connect(self._db_path)
                    try:
                        row = conn.execute(
                            """
                            SELECT text FROM conversation_entries
                            WHERE project = ? AND chat_id = ? AND role = 'job_result' AND job_id = ?
                            ORDER BY id DESC LIMIT 1
                            """,
                            (project, chat_id, str(job_id)),
                        ).fetchone()
                    finally:
                        conn.close()
                job_result = str(row[0]) if row is not None else None
            else:
                job_result = self.get_latest_job_result_text_for_user_message(
                    project, chat_id, message_id
                )
            result.append((user_entry.text, job_result))
        return result

    def generate_report(
        self,
        project: str,
        chat_id: int,
        recent_limit: int = 5,
    ) -> ConversationReport | None:
        safe_limit = max(0, recent_limit)
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                total_entries = int(
                    conn.execute(
                        """
                        SELECT COUNT(*)
                        FROM conversation_entries
                        WHERE project = ? AND chat_id = ?
                        """,
                        (project, chat_id),
                    ).fetchone()[0]
                )
                if total_entries == 0:
                    return None

                role_rows = conn.execute(
                    """
                    SELECT role, COUNT(*)
                    FROM conversation_entries
                    WHERE project = ? AND chat_id = ?
                    GROUP BY role
                    ORDER BY role
                    """,
                    (project, chat_id),
                ).fetchall()
                latest_user_row = conn.execute(
                    """
                    SELECT text
                    FROM conversation_entries
                    WHERE project = ? AND chat_id = ? AND role = 'user'
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (project, chat_id),
                ).fetchone()
                latest_job_row = conn.execute(
                    """
                    SELECT job_id, text
                    FROM conversation_entries
                    WHERE project = ? AND chat_id = ? AND role = 'job_result'
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (project, chat_id),
                ).fetchone()
                recent_rows: list[tuple[object, ...]] = []
                if safe_limit > 0:
                    recent_rows = conn.execute(
                        """
                        SELECT id, project, chat_id, role, text, job_id, message_id, reply_to_message_id
                        FROM conversation_entries
                        WHERE project = ? AND chat_id = ?
                        ORDER BY id DESC
                        LIMIT ?
                        """,
                        (project, chat_id, safe_limit),
                    ).fetchall()
            finally:
                conn.close()

        recent_rows.reverse()
        return ConversationReport(
            project=project,
            chat_id=chat_id,
            total_entries=total_entries,
            role_counts=[
                ConversationRoleCount(role=str(role), count=int(count)) for role, count in role_rows
            ],
            latest_user_text=str(latest_user_row[0]) if latest_user_row is not None else None,
            latest_job_id=str(latest_job_row[0]) if latest_job_row and latest_job_row[0] else None,
            latest_job_result=str(latest_job_row[1]) if latest_job_row is not None else None,
            recent_entries=[_row_to_entry(r) for r in recent_rows],
        )

    def get_chat_stats(self, project: str, chat_id: int) -> ConversationDbChatStats:
        db_exists = self._db_path.exists()
        size_bytes = self._db_path.stat().st_size if db_exists else 0
        rows_by_role: dict[str, int] = {}
        total_rows = 0
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                total_rows = int(
                    conn.execute(
                        """
                        SELECT COUNT(*)
                        FROM conversation_entries
                        WHERE project = ? AND chat_id = ?
                        """,
                        (project, chat_id),
                    ).fetchone()[0]
                )
                for role, cnt in conn.execute(
                    """
                    SELECT role, COUNT(*)
                    FROM conversation_entries
                    WHERE project = ? AND chat_id = ?
                    GROUP BY role
                    ORDER BY role
                    """,
                    (project, chat_id),
                ).fetchall():
                    rows_by_role[str(role)] = int(cnt)
            finally:
                conn.close()
        return ConversationDbChatStats(
            db_path=self._db_path,
            db_exists=db_exists,
            db_size_bytes=size_bytes,
            total_rows=total_rows,
            rows_by_role=rows_by_role,
        )


def _row_to_entry(r: tuple[object, ...]) -> ConversationEntry:
    return ConversationEntry(
        id=int(r[0]),
        project=str(r[1]),
        chat_id=int(r[2]),
        role=str(r[3]),
        text=str(r[4]),
        job_id=str(r[5]) if r[5] is not None else None,
        message_id=int(r[6]) if len(r) > 6 and r[6] is not None else None,
        reply_to_message_id=int(r[7]) if len(r) > 7 and r[7] is not None else None,
    )


class ConversationContextBuilder:
    @staticmethod
    def build(entries: list[ConversationEntry], current_user_line: str) -> str:
        lines: list[str] = [
            "[이전 대화/작업 맥락]",
        ]
        for e in entries:
            label = e.role
            if e.job_id:
                label = f"{e.role} (job_id={e.job_id})"
            snippet = _truncate_snippet(e.text, 800)
            lines.append(f"{label}: {snippet}")
        lines.extend(
            [
                "[/이전 대화]",
                "",
                "[현재 요청]",
                current_user_line.strip(),
                "[/현재 요청]",
            ]
        )
        return "\n".join(lines)
