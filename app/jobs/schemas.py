from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field

from app.models import ModelName


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobRequest(BaseModel):
    project: str
    model: ModelName
    instruction: str
    branch: str | None = None
    commit: bool = True
    chat_id: int
    requested_by: int | None = None
    message_id: int | None = None
    reply_to_message_id: int | None = None


class Job(BaseModel):
    id: str
    request: JobRequest
    status: JobStatus = JobStatus.QUEUED
    branch: str | None = None
    commit_hash: str | None = None
    changed_files: list[str] = Field(default_factory=list)
    error: str | None = None
    error_stage: str | None = None
    runner_stdout_summary: str | None = None
    runner_stderr_summary: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    finished_at: datetime | None = None
    log_path: Path | None = None

    def mark_running(self) -> None:
        if self.status != JobStatus.QUEUED:
            raise ValueError(f"Cannot move {self.status} to running")
        self.status = JobStatus.RUNNING
        self.started_at = datetime.now(UTC)

    def mark_succeeded(self) -> None:
        if self.status != JobStatus.RUNNING:
            raise ValueError(f"Cannot move {self.status} to succeeded")
        self.status = JobStatus.SUCCEEDED
        self.finished_at = datetime.now(UTC)

    def mark_failed(self, error: str) -> None:
        if self.status not in (JobStatus.QUEUED, JobStatus.RUNNING):
            raise ValueError(f"Cannot move {self.status} to failed")
        self.status = JobStatus.FAILED
        self.error = error
        self.finished_at = datetime.now(UTC)


class JobResult(BaseModel):
    success: bool
    project: str
    branch: str | None = None
    commit_hash: str | None = None
    changed_files: list[str] = Field(default_factory=list)
    error_summary: str | None = None
