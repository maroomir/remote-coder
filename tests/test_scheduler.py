from datetime import UTC, datetime, timedelta

from app.jobs.schedule import ScheduleRecord
from app.jobs.schedule_store import InMemoryScheduleStore
from app.jobs.scheduler import JobScheduler, build_scheduled_job_request
from app.jobs.schemas import JobMode, JobRequest
from app.models import ModelName


def _record(**overrides) -> ScheduleRecord:
    base = dict(
        id="sch-1",
        project="proj",
        chat_id=7,
        requested_by=7,
        mode=JobMode.RESEARCH,
        model=ModelName.CLAUDE,
        instruction="audit dependencies",
        interval_seconds=3600,
    )
    base.update(overrides)
    return ScheduleRecord(**base)


def test_build_request_is_read_only_and_no_commit():
    request = build_scheduled_job_request(_record(mode=JobMode.ASK))
    assert request.mode is JobMode.ASK
    assert request.commit is False
    assert request.branch is None
    assert request.project == "proj"
    assert request.instruction == "audit dependencies"


def test_due_schedule_fires_and_advances_next_run():
    store = InMemoryScheduleStore()
    store.create(_record(next_run_at=None))
    submitted: list[JobRequest] = []
    scheduler = JobScheduler(
        schedule_store=store,
        submit_and_run=lambda req: submitted.append(req) or None,
    )

    now = datetime(2026, 6, 22, 8, 0, tzinfo=UTC)
    fired = scheduler.run_due_schedules(now=now)

    assert fired == 1
    assert len(submitted) == 1
    updated = store.get("sch-1")
    assert updated.last_run_at == now
    assert updated.next_run_at == now + timedelta(seconds=3600)


def test_not_due_schedule_does_not_fire():
    store = InMemoryScheduleStore()
    now = datetime(2026, 6, 22, 8, 0, tzinfo=UTC)
    store.create(_record(next_run_at=now + timedelta(hours=1)))
    submitted: list[JobRequest] = []
    scheduler = JobScheduler(
        schedule_store=store,
        submit_and_run=lambda req: submitted.append(req) or None,
    )

    assert scheduler.run_due_schedules(now=now) == 0
    assert submitted == []


def test_disabled_schedule_does_not_fire():
    store = InMemoryScheduleStore()
    store.create(_record(enabled=False, next_run_at=None))
    submitted: list[JobRequest] = []
    scheduler = JobScheduler(
        schedule_store=store,
        submit_and_run=lambda req: submitted.append(req) or None,
    )

    assert scheduler.run_due_schedules() == 0
    assert submitted == []


def test_next_run_advances_before_job_runs():
    # The schedule clock must advance even if the job submission itself raises, so a failing
    # scheduled job does not re-fire on every poll.
    store = InMemoryScheduleStore()
    store.create(_record(next_run_at=None))

    def boom(_request):
        raise RuntimeError("submission failed")

    scheduler = JobScheduler(schedule_store=store, submit_and_run=boom)
    now = datetime(2026, 6, 22, 8, 0, tzinfo=UTC)

    fired = scheduler.run_due_schedules(now=now)

    assert fired == 1
    updated = store.get("sch-1")
    assert updated.next_run_at == now + timedelta(seconds=3600)


def test_start_and_stop_are_safe_and_idempotent():
    store = InMemoryScheduleStore()
    scheduler = JobScheduler(
        schedule_store=store,
        submit_and_run=lambda _req: None,
        poll_interval_seconds=0.05,
    )
    scheduler.start()
    scheduler.start()  # idempotent: second start is a no-op
    scheduler.stop()
    # stop must be safe to call again after the thread is gone.
    scheduler.stop()


def test_one_bad_schedule_does_not_block_others():
    store = InMemoryScheduleStore()
    store.create(_record(id="bad", next_run_at=None))
    store.create(_record(id="good", next_run_at=None))
    submitted: list[str] = []

    def submit(request: JobRequest):
        # The first schedule (created first) is "bad" and raises; the second must still fire.
        if not submitted:
            submitted.append("bad")
            raise RuntimeError("boom")
        submitted.append("good")
        return None

    scheduler = JobScheduler(schedule_store=store, submit_and_run=submit)
    fired = scheduler.run_due_schedules()

    assert fired == 2
    assert submitted == ["bad", "good"]
