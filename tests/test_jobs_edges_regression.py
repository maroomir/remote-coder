"""Regression tests for edges the feature suite does not otherwise cover.

These probe narrow behaviours the job/scheduling features promise but assert nowhere else: the
bare branch-op in-flight guard, scheduler no-double-fire / catch-up semantics, the `/schedule`
interval upper bound, the empty diff-review summary, and the validation gate running as plain
argv (never a shell).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

from app.git.branch_ops_lock import acquire_branch_op, release_branch_op
from app.jobs.diff_review import build_diff_review_summary
from app.jobs.schedule import ScheduleRecord
from app.jobs.schedule_store import InMemoryScheduleStore
from app.jobs.scheduler import JobScheduler
from app.jobs.schemas import JobMode, JobRequest
from app.jobs.validation import run_validation_command
from app.models import ModelName
from app.projects.registry import ProjectRegistry
from app.telegram.commands import CommandContext, TelegramMessage
from app.telegram.commands.schedule import ScheduleCommand
from app.telegram.confirmations import InMemoryConfirmationStore
from app.telegram.model_preferences import InMemoryModelPreferenceStore


# --- A1: branch_ops_lock --------------------------------------------------------------------


def test_branch_op_double_acquire_blocks_then_release_frees():
    key = ("/repo/x", "origin", "remote-feature")
    assert acquire_branch_op(key) is True
    try:
        # A second acquire of the same key must be refused while the first is in flight.
        assert acquire_branch_op(key) is False
    finally:
        release_branch_op(key)
    # Once released, the key is acquirable again.
    assert acquire_branch_op(key) is True
    release_branch_op(key)


def test_branch_op_independent_keys_do_not_block():
    a = ("/repo/x", "origin", "branch-a")
    b = ("/repo/x", "origin", "branch-b")
    assert acquire_branch_op(a) is True
    assert acquire_branch_op(b) is True
    release_branch_op(a)
    release_branch_op(b)


def test_branch_op_release_is_idempotent():
    key = ("/repo/x", "origin", "branch-z")
    # Releasing a key that was never acquired must not raise.
    release_branch_op(key)
    assert acquire_branch_op(key) is True
    release_branch_op(key)
    release_branch_op(key)


# --- A2/A3: scheduler timing ----------------------------------------------------------------


def _schedule(**overrides) -> ScheduleRecord:
    base = dict(
        id="sch-adv",
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


def test_schedule_fires_once_then_waits_for_next_interval():
    """A due schedule fired at T must not re-fire on a poll at the same T (advance-before-run)."""
    store = InMemoryScheduleStore()
    store.create(_schedule(next_run_at=None))
    submitted: list[JobRequest] = []
    scheduler = JobScheduler(
        schedule_store=store, submit_and_run=lambda req: submitted.append(req) or None
    )
    now = datetime(2026, 6, 22, 8, 0, tzinfo=UTC)

    assert scheduler.run_due_schedules(now=now) == 1
    # Immediate re-poll at the same instant: next_run advanced to now+interval, so nothing fires.
    assert scheduler.run_due_schedules(now=now) == 0
    # Just before the next interval boundary still nothing; at the boundary it fires again.
    assert scheduler.run_due_schedules(now=now + timedelta(seconds=3599)) == 0
    assert scheduler.run_due_schedules(now=now + timedelta(seconds=3600)) == 1
    assert len(submitted) == 2


def test_stale_past_schedule_fires_once_not_per_missed_interval():
    """After long downtime, a schedule whose next_run is far in the past fires once, not N times."""
    store = InMemoryScheduleStore()
    long_ago = datetime(2026, 6, 22, 0, 0, tzinfo=UTC)
    store.create(_schedule(interval_seconds=3600, next_run_at=long_ago))
    fired: list[JobRequest] = []
    scheduler = JobScheduler(
        schedule_store=store, submit_and_run=lambda req: fired.append(req) or None
    )
    # 8h after the missed slot (8 intervals skipped) — must still only fire once this poll.
    now = long_ago + timedelta(hours=8)
    assert scheduler.run_due_schedules(now=now) == 1
    assert scheduler.run_due_schedules(now=now) == 0
    assert len(fired) == 1
    # next_run is rebased on the poll time, not the stale slot, so it is in the future.
    assert store.get("sch-adv").next_run_at == now + timedelta(seconds=3600)


# --- A4/A5: /schedule interval bounds --------------------------------------------------------


def _ctx(project_registry: ProjectRegistry, store: InMemoryScheduleStore) -> CommandContext:
    return CommandContext(
        job_store=Mock(),
        default_model=ModelName.CLAUDE,
        project_registry=project_registry,
        model_preferences=InMemoryModelPreferenceStore(default_model=ModelName.CLAUDE),
        project_name=project_registry.get_default_project_name(),
        git_service=Mock(),
        git_remote_name="origin",
        conversation_store=None,
        confirmation_store=InMemoryConfirmationStore(),
        advanced_settings_store=None,
        schedule_store=store,
    )


def test_schedule_command_rejects_interval_above_max(project_registry: ProjectRegistry):
    store = InMemoryScheduleStore()
    ctx = _ctx(project_registry, store)
    # 400d is above the 365d cap: must be refused so no never-firing schedule is created.
    text = ScheduleCommand().execute(
        TelegramMessage(chat_id=1, user_id=1, text="/schedule 400d research audit"), ctx
    )
    assert "Interval must be" in text
    assert store.list_for_project_chat(project_registry.get_default_project_name(), 1) == []


def test_schedule_command_rejects_zero_interval(project_registry: ProjectRegistry):
    store = InMemoryScheduleStore()
    ctx = _ctx(project_registry, store)
    text = ScheduleCommand().execute(
        TelegramMessage(chat_id=1, user_id=1, text="/schedule 0d research audit"), ctx
    )
    assert "Interval must be" in text
    assert store.list_for_project_chat(project_registry.get_default_project_name(), 1) == []


def test_schedule_command_accepts_one_minute_boundary(project_registry: ProjectRegistry):
    store = InMemoryScheduleStore()
    ctx = _ctx(project_registry, store)
    # 1m == the 60s floor: inclusive lower bound must be accepted.
    text = ScheduleCommand().execute(
        TelegramMessage(chat_id=1, user_id=1, text="/schedule 1m ask quick check"), ctx
    )
    assert "Scheduled" in text
    schedules = store.list_for_project_chat(project_registry.get_default_project_name(), 1)
    assert len(schedules) == 1
    assert schedules[0].interval_seconds == 60


# --- A7: diff review empty input ------------------------------------------------------------


def test_diff_review_empty_input_is_empty_summary():
    summary = build_diff_review_summary([])
    assert summary.file_count == 0
    assert summary.total_added == 0
    assert summary.total_deleted == 0
    assert summary.risk_flags == []


# --- A8: validation gate uses argv, not a shell ---------------------------------------------


def test_validation_command_runs_as_argv_not_shell(tmp_path: Path):
    """A `;`-chained `rm` is passed as literal argv (no shell), so the injection never executes.

    Confirms a configured validation command cannot smuggle shell operators into a real shell:
    `echo` receives `;`, `rm`, and the path as plain arguments and the sentinel survives.
    """
    sentinel = tmp_path / "canary.txt"
    sentinel.write_text("intact", encoding="utf-8")
    result = run_validation_command(f"echo start ; rm {sentinel}", tmp_path, timeout_seconds=10)
    # The decisive security invariant: no shell interpreted ';', so the rm never ran.
    assert sentinel.exists()
    assert sentinel.read_text(encoding="utf-8") == "intact"
    # The metacharacters were handed to `echo` as literal text instead of being executed.
    assert "rm" in result.output_summary
