from __future__ import annotations

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
