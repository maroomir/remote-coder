from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.jobs.schedule import MIN_INTERVAL_SECONDS, ScheduleRecord
from app.jobs.schedule_store import InMemoryScheduleStore, SQLiteScheduleStore
from app.jobs.schemas import JobMode
from app.models import ModelName


def _record(**overrides) -> ScheduleRecord:
    base = dict(
        id="sch-1",
        project="proj",
        chat_id=1,
        requested_by=1,
        mode=JobMode.RESEARCH,
        model=ModelName.CLAUDE,
        instruction="check dependencies",
        interval_seconds=3600,
    )
    base.update(overrides)
    return ScheduleRecord(**base)


def test_read_only_modes_are_accepted():
    for mode in (JobMode.RESEARCH, JobMode.ASK, JobMode.PLAN):
        rec = _record(mode=mode)
        assert rec.mode is mode


def test_write_modes_are_rejected():
    for mode in (JobMode.AGENT, JobMode.AGENT_FIX):
        with pytest.raises(ValidationError, match="read-only"):
            _record(mode=mode)


def test_interval_below_minimum_is_rejected():
    with pytest.raises(ValidationError, match="at least"):
        _record(interval_seconds=MIN_INTERVAL_SECONDS - 1)


def test_is_due_when_next_run_unset():
    rec = _record(next_run_at=None)
    assert rec.is_due()


def test_is_due_respects_next_run_at():
    now = datetime.now(UTC)
    not_yet = _record(next_run_at=now + timedelta(hours=1))
    assert not not_yet.is_due(now=now)
    overdue = _record(next_run_at=now - timedelta(seconds=1))
    assert overdue.is_due(now=now)


def test_disabled_schedule_is_never_due():
    rec = _record(enabled=False, next_run_at=None)
    assert not rec.is_due()


def test_compute_next_run_adds_interval():
    base = datetime(2026, 6, 22, 8, 0, tzinfo=UTC)
    rec = _record(interval_seconds=1800)
    assert rec.compute_next_run(after=base) == base + timedelta(seconds=1800)


@pytest.mark.parametrize("store_factory", ["memory", "sqlite"])
def test_store_create_get_update_delete(store_factory, tmp_path):
    store = (
        InMemoryScheduleStore()
        if store_factory == "memory"
        else SQLiteScheduleStore(tmp_path / "schedules.sqlite3")
    )
    rec = _record()
    store.create(rec)

    fetched = store.get("sch-1")
    assert fetched is not None
    assert fetched.instruction == "check dependencies"

    fetched.enabled = False
    store.update(fetched)
    assert store.get("sch-1").enabled is False

    assert store.delete("sch-1") is True
    assert store.get("sch-1") is None
    assert store.delete("sch-1") is False


@pytest.mark.parametrize("store_factory", ["memory", "sqlite"])
def test_store_list_for_project_chat_and_enabled(store_factory, tmp_path):
    store = (
        InMemoryScheduleStore()
        if store_factory == "memory"
        else SQLiteScheduleStore(tmp_path / "schedules.sqlite3")
    )
    store.create(_record(id="a", project="p", chat_id=1))
    store.create(_record(id="b", project="p", chat_id=1, enabled=False))
    store.create(_record(id="c", project="p", chat_id=2))
    store.create(_record(id="d", project="other", chat_id=1))

    for_p1 = store.list_for_project_chat("p", 1)
    assert {s.id for s in for_p1} == {"a", "b"}

    enabled = store.list_enabled()
    assert {s.id for s in enabled} == {"a", "c", "d"}


def test_sqlite_schedule_persists_across_instances(tmp_path):
    path = tmp_path / "schedules.sqlite3"
    SQLiteScheduleStore(path).create(_record(id="persist"))

    reopened = SQLiteScheduleStore(path)
    assert reopened.get("persist") is not None
