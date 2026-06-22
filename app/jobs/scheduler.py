from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import UTC, datetime

from app.jobs.schedule import ScheduleRecord
from app.jobs.schedule_store import ScheduleStore
from app.jobs.schemas import Job, JobRequest
from app.monitoring.events import EventLogger

_schedlog = EventLogger("app.jobs.scheduler", "job.scheduler")

# How often the scheduler thread wakes to look for due schedules. Schedules fire on their own
# interval; this only bounds the lag between "due" and "submitted".
DEFAULT_POLL_INTERVAL_SECONDS = 30.0


def build_scheduled_job_request(schedule: ScheduleRecord) -> JobRequest:
    """Turn a schedule into a fresh read-only job request.

    Read-only modes never branch, commit, or push, so the request carries no branch and
    `commit=False`; the ScheduleRecord validator already guarantees the mode is read-only.
    """
    return JobRequest(
        project=schedule.project,
        model=schedule.model,
        instruction=schedule.instruction,
        mode=schedule.mode,
        chat_id=schedule.chat_id,
        requested_by=schedule.requested_by,
        commit=False,
    )


class JobScheduler:
    def __init__(
        self,
        *,
        schedule_store: ScheduleStore,
        submit_and_run: Callable[[JobRequest], Job | None],
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
    ) -> None:
        self._schedule_store = schedule_store
        self._submit_and_run = submit_and_run
        self._poll_interval_seconds = poll_interval_seconds
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop, name="remote-coder-scheduler", daemon=True
        )
        self._thread.start()
        _schedlog.info("scheduler started poll=%.0fs", self._poll_interval_seconds)

    def stop(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=self._poll_interval_seconds + 5)
        self._thread = None
        _schedlog.info("scheduler stopped")

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.run_due_schedules()
            except Exception:  # pylint: disable=broad-except
                # A single bad schedule must never kill the scheduler thread; log and continue.
                _schedlog.exception("scheduler tick failed")
            self._stop_event.wait(self._poll_interval_seconds)

    def run_due_schedules(self, now: datetime | None = None) -> int:
        """Submit a job for every due, enabled schedule. Returns how many fired."""
        current = now or datetime.now(UTC)
        fired = 0
        for schedule in self._schedule_store.list_enabled():
            if not schedule.is_due(current):
                continue
            self._fire(schedule, current)
            fired += 1
        return fired

    def _fire(self, schedule: ScheduleRecord, fired_at: datetime) -> None:
        # Advance the schedule's clock BEFORE running the job so a long-running job cannot cause
        # the same schedule to re-fire on the next poll, and so a crash mid-run does not lose the
        # interval. The job itself runs under the JobManager's per-project lock.
        schedule.last_run_at = fired_at
        schedule.next_run_at = schedule.compute_next_run(after=fired_at)
        self._schedule_store.update(schedule)
        _schedlog.info(
            "schedule firing mode=%s next=%s",
            schedule.mode.value,
            schedule.next_run_at.isoformat() if schedule.next_run_at else "-",
            project=schedule.project,
            chat_id=schedule.chat_id,
        )
        request = build_scheduled_job_request(schedule)
        try:
            self._submit_and_run(request)
        except Exception:  # pylint: disable=broad-except
            _schedlog.exception(
                "scheduled job submission failed",
                project=schedule.project,
                chat_id=schedule.chat_id,
            )
