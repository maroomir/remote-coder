from __future__ import annotations

import sqlite3
from pathlib import Path
from threading import Lock
from typing import Protocol

from app.jobs.schemas import Job, JobStatus


class JobStore(Protocol):
    def create(self, job: Job) -> None:
        ...

    def get(self, job_id: str) -> Job | None:
        ...

    def update(self, job: Job) -> None:
        ...

    def list_recent(self, limit: int = 20) -> list[Job]:
        ...

    def get_latest_succeeded_branch_for_project_chat(
        self, project: str, chat_id: int
    ) -> str | None:
        ...

    def list_succeeded_branches_for_project_chat(
        self, project: str, chat_id: int
    ) -> list[str]:
        ...

    def list_recent_for_chat(self, chat_id: int, limit: int = 20) -> list[Job]:
        ...

    def list_recent_for_project_chat(self, project: str, chat_id: int, limit: int = 20) -> list[Job]:
        ...


class InMemoryJobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, list[Job]] = {}
        self._lock = Lock()

    def create(self, job: Job) -> None:
        with self._lock:
            self._jobs.setdefault(job.id, []).append(job)

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            jobs = self._jobs.get(job_id)
            return jobs[-1] if jobs else None

    def update(self, job: Job) -> None:
        with self._lock:
            jobs = self._jobs.get(job.id)
            if not jobs:
                self._jobs[job.id] = [job]
                return
            for idx, existing in enumerate(jobs):
                if existing.created_at == job.created_at:
                    jobs[idx] = job
                    return
            jobs[-1] = job

    def _all_jobs(self) -> list[Job]:
        return [job for jobs in self._jobs.values() for job in jobs]

    def list_recent(self, limit: int = 20) -> list[Job]:
        with self._lock:
            values = sorted(self._all_jobs(), key=lambda job: job.created_at, reverse=True)
            return values[:limit]

    def list_recent_for_chat(self, chat_id: int, limit: int = 20) -> list[Job]:
        with self._lock:
            values = [
                job
                for job in self._all_jobs()
                if job.request.chat_id == chat_id
            ]
            values.sort(key=lambda job: job.created_at, reverse=True)
            return values[:limit]

    def list_recent_for_project_chat(self, project: str, chat_id: int, limit: int = 20) -> list[Job]:
        with self._lock:
            values = [
                job
                for job in self._all_jobs()
                if job.request.project == project and job.request.chat_id == chat_id
            ]
            values.sort(key=lambda job: job.created_at, reverse=True)
            return values[:limit]

    def get_latest_succeeded_branch_for_project_chat(
        self, project: str, chat_id: int
    ) -> str | None:
        with self._lock:
            candidates = [
                j
                for j in self._all_jobs()
                if j.request.project == project
                and j.request.chat_id == chat_id
                and j.status == JobStatus.SUCCEEDED
                and j.branch
            ]
            if not candidates:
                return None
            candidates.sort(
                key=lambda j: (j.finished_at or j.created_at, j.created_at),
                reverse=True,
            )
            return candidates[0].branch

    def list_succeeded_branches_for_project_chat(
        self, project: str, chat_id: int
    ) -> list[str]:
        with self._lock:
            candidates = [
                job
                for job in self._all_jobs()
                if job.request.project == project
                and job.request.chat_id == chat_id
                and job.status == JobStatus.SUCCEEDED
                and job.branch
            ]
            candidates.sort(
                key=lambda job: (job.finished_at or job.created_at, job.created_at),
                reverse=True,
            )
            branches: list[str] = []
            seen: set[str] = set()
            for job in candidates:
                branch = job.branch
                if branch is not None and branch not in seen:
                    seen.add(branch)
                    branches.append(branch)
            return branches


def _job_to_payload(job: Job) -> str:
    return job.model_dump_json()


def _payload_to_job(payload: str) -> Job:
    return Job.model_validate_json(payload)


def _job_sort_timestamp(job: Job) -> str:
    return job.created_at.isoformat()


def _job_finish_sort_timestamp(job: Job) -> str | None:
    return (job.finished_at or job.created_at).isoformat()


class SQLiteJobStore:
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
                    CREATE TABLE IF NOT EXISTS jobs (
                        row_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        job_id TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        finished_at TEXT,
                        request_project TEXT NOT NULL,
                        request_chat_id INTEGER NOT NULL,
                        status TEXT NOT NULL,
                        branch TEXT,
                        commit_hash TEXT,
                        payload TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_job_created
                    ON jobs (job_id, created_at)
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_jobs_recent
                    ON jobs (created_at DESC, row_id DESC)
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_jobs_project_chat_recent
                    ON jobs (request_project, request_chat_id, created_at DESC, row_id DESC)
                    """
                )
                conn.commit()
            finally:
                conn.close()

    def create(self, job: Job) -> None:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                self._insert_job(conn, job)
                conn.commit()
            finally:
                conn.close()

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                row = conn.execute(
                    """
                    SELECT payload
                    FROM jobs
                    WHERE job_id = ?
                    ORDER BY created_at DESC, row_id DESC
                    LIMIT 1
                    """,
                    (job_id,),
                ).fetchone()
            finally:
                conn.close()
        return _payload_to_job(str(row[0])) if row else None

    def update(self, job: Job) -> None:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                cur = conn.execute(
                    """
                    UPDATE jobs
                    SET finished_at = ?,
                        request_project = ?,
                        request_chat_id = ?,
                        status = ?,
                        branch = ?,
                        commit_hash = ?,
                        payload = ?
                    WHERE job_id = ? AND created_at = ?
                    """,
                    self._row_values(job)[1:] + (job.id, _job_sort_timestamp(job)),
                )
                if cur.rowcount == 0:
                    self._insert_job(conn, job)
                conn.commit()
            finally:
                conn.close()

    def list_recent(self, limit: int = 20) -> list[Job]:
        if limit <= 0:
            return []
        return self._fetch_jobs(
            """
            SELECT payload
            FROM jobs
            ORDER BY created_at DESC, row_id DESC
            LIMIT ?
            """,
            (limit,),
        )

    def list_recent_for_chat(self, chat_id: int, limit: int = 20) -> list[Job]:
        if limit <= 0:
            return []
        return self._fetch_jobs(
            """
            SELECT payload
            FROM jobs
            WHERE request_chat_id = ?
            ORDER BY created_at DESC, row_id DESC
            LIMIT ?
            """,
            (chat_id, limit),
        )

    def list_recent_for_project_chat(self, project: str, chat_id: int, limit: int = 20) -> list[Job]:
        if limit <= 0:
            return []
        return self._fetch_jobs(
            """
            SELECT payload
            FROM jobs
            WHERE request_project = ? AND request_chat_id = ?
            ORDER BY created_at DESC, row_id DESC
            LIMIT ?
            """,
            (project, chat_id, limit),
        )

    def get_latest_succeeded_branch_for_project_chat(
        self, project: str, chat_id: int
    ) -> str | None:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                row = conn.execute(
                    """
                    SELECT branch
                    FROM jobs
                    WHERE request_project = ?
                      AND request_chat_id = ?
                      AND status = ?
                      AND branch IS NOT NULL
                    ORDER BY COALESCE(finished_at, created_at) DESC, created_at DESC, row_id DESC
                    LIMIT 1
                    """,
                    (project, chat_id, JobStatus.SUCCEEDED.value),
                ).fetchone()
            finally:
                conn.close()
        return str(row[0]) if row else None

    def list_succeeded_branches_for_project_chat(
        self, project: str, chat_id: int
    ) -> list[str]:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                rows = conn.execute(
                    """
                    SELECT branch
                    FROM jobs
                    WHERE request_project = ?
                      AND request_chat_id = ?
                      AND status = ?
                      AND branch IS NOT NULL
                    ORDER BY COALESCE(finished_at, created_at) DESC, created_at DESC, row_id DESC
                    """,
                    (project, chat_id, JobStatus.SUCCEEDED.value),
                ).fetchall()
            finally:
                conn.close()
        branches: list[str] = []
        seen: set[str] = set()
        for row in rows:
            branch = str(row[0])
            if branch not in seen:
                seen.add(branch)
                branches.append(branch)
        return branches

    @staticmethod
    def _row_values(job: Job) -> tuple[str, str | None, str, int, str, str | None, str | None, str]:
        return (
            _job_sort_timestamp(job),
            _job_finish_sort_timestamp(job),
            job.request.project,
            job.request.chat_id,
            job.status.value,
            job.branch,
            job.commit_hash,
            _job_to_payload(job),
        )

    def _insert_job(self, conn: sqlite3.Connection, job: Job) -> None:
        conn.execute(
            """
            INSERT INTO jobs (
                job_id,
                created_at,
                finished_at,
                request_project,
                request_chat_id,
                status,
                branch,
                commit_hash,
                payload
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (job.id,) + self._row_values(job),
        )

    def _fetch_jobs(self, query: str, params: tuple[object, ...]) -> list[Job]:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                rows = conn.execute(query, params).fetchall()
            finally:
                conn.close()
        return [_payload_to_job(str(row[0])) for row in rows]
