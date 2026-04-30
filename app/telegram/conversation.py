from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from threading import Lock


_AMBIGUOUS_FOLLOWUP = re.compile(
    r"^\s*(작업\s*시작해줘|진행해줘|그거\s*해줘|시작해줘)\s*$",
    re.UNICODE | re.IGNORECASE,
)


def is_ambiguous_followup(text: str) -> bool:
    """옵션 제거 후 남은 본문이 모호한 후속 요청인지 여부."""
    return bool(_AMBIGUOUS_FOLLOWUP.match(text.strip()))


@dataclass(frozen=True)
class ConversationEntry:
    """프로젝트+채팅별 대화/작업 기록 한 줄."""

    id: int
    project: str
    chat_id: int
    role: str
    text: str
    job_id: str | None


@dataclass(frozen=True)
class ConversationRoleCount:
    role: str
    count: int


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


class SQLiteConversationStore:
    """프로젝트 이름과 텔레그램 chat_id 단위로 SQLite에 대화를 저장합니다."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path.resolve()
        self._lock = Lock()
        self.ensure_schema()

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
                        created_at TEXT NOT NULL DEFAULT (datetime('now'))
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_conversation_project_chat_id
                    ON conversation_entries (project, chat_id, id)
                    """
                )
                conn.commit()
            finally:
                conn.close()

    def reset(self) -> None:
        """기억 DB 파일을 비우고 빈 스키마로 다시 만듭니다."""
        with self._lock:
            if self._db_path.exists():
                self._db_path.unlink()
        self.ensure_schema()

    def append(
        self,
        *,
        project: str,
        chat_id: int,
        role: str,
        text: str,
        job_id: str | None = None,
    ) -> None:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                conn.execute(
                    """
                    INSERT INTO conversation_entries (project, chat_id, role, text, job_id)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (project, chat_id, role, text, job_id),
                )
                conn.commit()
            finally:
                conn.close()

    def list_recent(self, project: str, chat_id: int, limit: int) -> list[ConversationEntry]:
        """해당 프로젝트+채팅의 최근 limit개를 id 오름차순(시간순)으로 반환합니다."""
        if limit <= 0:
            return []
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                cur = conn.execute(
                    """
                    SELECT id, project, chat_id, role, text, job_id
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
        return [
            ConversationEntry(
                id=int(r[0]),
                project=str(r[1]),
                chat_id=int(r[2]),
                role=str(r[3]),
                text=str(r[4]),
                job_id=str(r[5]) if r[5] is not None else None,
            )
            for r in rows
        ]

    def generate_report(
        self,
        project: str,
        chat_id: int,
        recent_limit: int = 5,
    ) -> ConversationReport | None:
        """SQL 집계로 프로젝트+채팅별 기억 요약 리포트를 생성합니다."""
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
                        SELECT id, project, chat_id, role, text, job_id
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
            recent_entries=[
                ConversationEntry(
                    id=int(r[0]),
                    project=str(r[1]),
                    chat_id=int(r[2]),
                    role=str(r[3]),
                    text=str(r[4]),
                    job_id=str(r[5]) if r[5] is not None else None,
                )
                for r in recent_rows
            ],
        )


class ConversationContextBuilder:
    """최근 기록과 현재 한 줄 요청을 runner instruction 문자열로 합칩니다."""

    @staticmethod
    def build(entries: list[ConversationEntry], current_user_line: str) -> str:
        lines: list[str] = [
            "[이전 대화/작업 맥락]",
        ]
        for e in entries:
            label = e.role
            if e.job_id:
                label = f"{e.role} (job_id={e.job_id})"
            # 한 줄씩 짧게 유지해 토큰 낭비를 줄입니다.
            snippet = e.text.strip().replace("\r\n", "\n").replace("\r", "\n")
            if len(snippet) > 800:
                snippet = snippet[:800].rstrip() + "...(truncated)"
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
