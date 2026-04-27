from __future__ import annotations

from threading import Lock
from typing import Protocol

from app.jobs.schemas import Job


class JobStore(Protocol):
    def create(self, job: Job) -> None:
        ...

    def get(self, job_id: str) -> Job | None:
        ...

    def update(self, job: Job) -> None:
        ...

    def list_recent(self, limit: int = 20) -> list[Job]:
        ...


class InMemoryJobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = Lock()

    def create(self, job: Job) -> None:
        with self._lock:
            self._jobs[job.id] = job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def update(self, job: Job) -> None:
        with self._lock:
            self._jobs[job.id] = job

    def list_recent(self, limit: int = 20) -> list[Job]:
        with self._lock:
            values = sorted(self._jobs.values(), key=lambda job: job.created_at, reverse=True)
            return values[:limit]
