from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

from app.models import ModelName

_SAFE_BRANCH_TOKEN = re.compile(r"^[A-Za-z0-9/._-]+$")
_SAFE_JOB_ID_TOKEN = re.compile(r"^[A-Za-z0-9_.-]+$")
_SAFE_SESSION_TOKEN = re.compile(r"^[A-Za-z0-9_.:-]+$")


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobMode(StrEnum):
    AGENT = "agent"
    PLAN = "plan"
    ASK = "ask"
    AGENT_FIX = "agent_fix"


class FixKind(StrEnum):
    SOURCE = "source"


class JobRequest(BaseModel):
    project: str
    model: ModelName
    model_id: str | None = None
    instruction: str
    mode: JobMode = JobMode.AGENT
    job_id: str | None = None
    branch: str | None = None
    commit: bool = True
    chat_id: int
    requested_by: int | None = None
    message_id: int | None = None
    reply_to_message_id: int | None = None
    parent_job_id: str | None = None
    fix_kind: FixKind | None = None
    session_id: str | None = None
    resume_session_token: str | None = None
    plan_decisions_resolved: bool = False

    @field_validator("branch")
    @classmethod
    def _validate_branch(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value or len(value) > 255:
            raise ValueError("branch is empty or too long")
        if ".." in value or value.startswith("-") or not _SAFE_BRANCH_TOKEN.match(value):
            raise ValueError("branch must use only ASCII letters, numbers, /, ., _, -")
        return value

    @field_validator("job_id", "parent_job_id")
    @classmethod
    def _validate_job_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value or len(value) > 128 or not _SAFE_JOB_ID_TOKEN.match(value):
            raise ValueError("job_id must use only ASCII letters, numbers, ., _, -")
        return value

    @field_validator("session_id", "resume_session_token")
    @classmethod
    def _validate_session_token(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value or len(value) > 128 or not _SAFE_SESSION_TOKEN.match(value):
            raise ValueError("session token must use only ASCII letters, numbers, ., :, _, -")
        return value


class Job(BaseModel):
    id: str
    request: JobRequest
    status: JobStatus = JobStatus.QUEUED
    branch: str | None = None
    commit_hash: str | None = None
    changed_files: list[str] = Field(default_factory=list)
    error: str | None = None
    error_stage: str | None = None
    runner_actual_model: str | None = None
    runner_token_usage: dict[str, int] = Field(default_factory=dict)
    runner_stdout_summary: str | None = None
    runner_stderr_summary: str | None = None
    runner_session_id: str | None = None
    accepted_message_id: int | None = None
    result_message_ids: list[int] = Field(default_factory=list)
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

    def mark_cancelled(self) -> None:
        if self.status not in (JobStatus.QUEUED, JobStatus.RUNNING):
            raise ValueError(f"Cannot move {self.status} to cancelled")
        self.status = JobStatus.CANCELLED
        self.finished_at = datetime.now(UTC)
