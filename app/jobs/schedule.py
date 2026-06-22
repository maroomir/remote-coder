from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, Field, field_validator

from app.jobs.schemas import JobMode, is_read_only_job_mode
from app.models import ModelName

# Minimum interval guards against accidentally hammering the AI CLI / provider quota with a
# too-frequent schedule. One minute is plenty for the "periodic check" use cases.
MIN_INTERVAL_SECONDS = 60


class ScheduleRecord(BaseModel):
    id: str
    project: str
    chat_id: int
    requested_by: int | None = None
    mode: JobMode
    model: ModelName
    instruction: str
    interval_seconds: int
    enabled: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None

    @field_validator("mode")
    @classmethod
    def _only_read_only_modes(cls, value: JobMode) -> JobMode:
        # Scheduled jobs run unattended, so they are restricted to read-only modes (no commits,
        # no pushes). Write modes must stay manual; a PLAN result still surfaces a Run-plan button.
        # Delegate to the same read-only check the execution pipeline uses so there is one source
        # of truth — a mode the pipeline would treat as writable can never be scheduled.
        if not is_read_only_job_mode(value):
            raise ValueError("scheduled jobs must use a read-only mode (ask, research, or plan)")
        return value

    @field_validator("interval_seconds")
    @classmethod
    def _interval_not_too_small(cls, value: int) -> int:
        if value < MIN_INTERVAL_SECONDS:
            raise ValueError(f"interval must be at least {MIN_INTERVAL_SECONDS} seconds")
        return value

    def compute_next_run(self, after: datetime | None = None) -> datetime:
        base = after or datetime.now(UTC)
        return base + timedelta(seconds=self.interval_seconds)

    def is_due(self, now: datetime | None = None) -> bool:
        if not self.enabled:
            return False
        current = now or datetime.now(UTC)
        if self.next_run_at is None:
            return True
        return current >= self.next_run_at
