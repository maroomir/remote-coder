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
