from __future__ import annotations

import sqlite3
from pathlib import Path
from threading import Lock
from typing import Protocol

from app.jobs.schedule import ScheduleRecord


class ScheduleStore(Protocol):
    def create(self, schedule: ScheduleRecord) -> None: ...

    def get(self, schedule_id: str) -> ScheduleRecord | None: ...

    def update(self, schedule: ScheduleRecord) -> None: ...

    def delete(self, schedule_id: str) -> bool: ...

    def list_for_project_chat(self, project: str, chat_id: int) -> list[ScheduleRecord]: ...

    def list_enabled(self) -> list[ScheduleRecord]: ...


class InMemoryScheduleStore:
    def __init__(self) -> None:
        self._schedules: dict[str, ScheduleRecord] = {}
        self._lock = Lock()

    def create(self, schedule: ScheduleRecord) -> None:
        with self._lock:
            self._schedules[schedule.id] = schedule.model_copy(deep=True)

    def get(self, schedule_id: str) -> ScheduleRecord | None:
        with self._lock:
            found = self._schedules.get(schedule_id)
            return found.model_copy(deep=True) if found else None

    def update(self, schedule: ScheduleRecord) -> None:
        with self._lock:
            self._schedules[schedule.id] = schedule.model_copy(deep=True)

    def delete(self, schedule_id: str) -> bool:
        with self._lock:
            return self._schedules.pop(schedule_id, None) is not None

    def list_for_project_chat(self, project: str, chat_id: int) -> list[ScheduleRecord]:
        with self._lock:
            matches = [
                s.model_copy(deep=True)
                for s in self._schedules.values()
                if s.project == project and s.chat_id == chat_id
            ]
        matches.sort(key=lambda s: s.created_at)
        return matches

    def list_enabled(self) -> list[ScheduleRecord]:
        with self._lock:
            matches = [s.model_copy(deep=True) for s in self._schedules.values() if s.enabled]
        matches.sort(key=lambda s: s.created_at)
        return matches


def _to_payload(schedule: ScheduleRecord) -> str:
    return schedule.model_dump_json()


def _from_payload(payload: str) -> ScheduleRecord:
    return ScheduleRecord.model_validate_json(payload)


class SQLiteScheduleStore:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path.resolve()
        self._lock = Lock()
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
                    CREATE TABLE IF NOT EXISTS schedules (
                        schedule_id TEXT PRIMARY KEY,
                        project TEXT NOT NULL,
                        chat_id INTEGER NOT NULL,
                        enabled INTEGER NOT NULL,
                        created_at TEXT NOT NULL,
                        payload TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_schedules_project_chat
                    ON schedules (project, chat_id, created_at)
                    """
                )
                conn.commit()
            finally:
                conn.close()

    def create(self, schedule: ScheduleRecord) -> None:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                conn.execute(
                    """
                    INSERT INTO schedules (schedule_id, project, chat_id, enabled, created_at, payload)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        schedule.id,
                        schedule.project,
                        schedule.chat_id,
                        int(schedule.enabled),
                        schedule.created_at.isoformat(),
                        _to_payload(schedule),
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    def get(self, schedule_id: str) -> ScheduleRecord | None:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                row = conn.execute(
                    "SELECT payload FROM schedules WHERE schedule_id = ?",
                    (schedule_id,),
                ).fetchone()
            finally:
                conn.close()
        return _from_payload(str(row[0])) if row else None

    def update(self, schedule: ScheduleRecord) -> None:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                conn.execute(
                    """
                    UPDATE schedules
                    SET project = ?, chat_id = ?, enabled = ?, created_at = ?, payload = ?
                    WHERE schedule_id = ?
                    """,
                    (
                        schedule.project,
                        schedule.chat_id,
                        int(schedule.enabled),
                        schedule.created_at.isoformat(),
                        _to_payload(schedule),
                        schedule.id,
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    def delete(self, schedule_id: str) -> bool:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                cur = conn.execute(
                    "DELETE FROM schedules WHERE schedule_id = ?", (schedule_id,)
                )
                conn.commit()
                return cur.rowcount > 0
            finally:
                conn.close()

    def list_for_project_chat(self, project: str, chat_id: int) -> list[ScheduleRecord]:
        return self._fetch(
            """
            SELECT payload FROM schedules
            WHERE project = ? AND chat_id = ?
            ORDER BY created_at ASC
            """,
            (project, chat_id),
        )

    def list_enabled(self) -> list[ScheduleRecord]:
        return self._fetch(
            """
            SELECT payload FROM schedules
            WHERE enabled = 1
            ORDER BY created_at ASC
            """,
            (),
        )

    def _fetch(self, query: str, params: tuple[object, ...]) -> list[ScheduleRecord]:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                rows = conn.execute(query, params).fetchall()
            finally:
                conn.close()
        return [_from_payload(str(row[0])) for row in rows]
