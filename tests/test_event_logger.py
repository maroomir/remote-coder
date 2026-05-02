import logging

import pytest

from app.monitoring.events import EventLogger
from app.monitoring.log_buffer import InMemoryLogBuffer, MemoryLogHandler


@pytest.fixture
def buf_and_logger() -> tuple[InMemoryLogBuffer, logging.Logger]:
    buf = InMemoryLogBuffer(max_entries=50)
    log = logging.getLogger("test_event_logger_unique")
    log.handlers.clear()
    log.setLevel(logging.INFO)
    log.propagate = False
    log.addHandler(MemoryLogHandler(buf))
    return buf, log


def test_event_logger_injects_category(buf_and_logger: tuple[InMemoryLogBuffer, logging.Logger]) -> None:
    buf, log = buf_and_logger
    ev = EventLogger(log.name, "job.lifecycle")
    ev.info("submitted", job_id="j1", chat_id=99)
    entries, _ = buf.query(limit=50, after_id=None, min_level=None, q=None, logger_sub=None)
    assert len(entries) == 1
    assert entries[0]["category"] == "job.lifecycle"
    assert entries[0]["job_id"] == "j1"
    assert entries[0]["chat_id"] == 99


def test_event_logger_ignores_non_whitelist_keys(buf_and_logger: tuple[InMemoryLogBuffer, logging.Logger]) -> None:
    buf, log = buf_and_logger
    ev = EventLogger(log.name, "telegram.inbound")
    # type: ignore[arg-type] — 의도적으로 허용되지 않은 키
    ev.info("msg", extra_unknown="should_not_appear")  # type: ignore[call-arg]
    entries, _ = buf.query(limit=50, after_id=None, min_level=None, q=None, logger_sub=None)
    assert len(entries) == 1
    assert "extra_unknown" not in entries[0]


def test_event_logger_exception_leaves_exc_in_buffer(buf_and_logger: tuple[InMemoryLogBuffer, logging.Logger]) -> None:
    buf, log = buf_and_logger
    ev = EventLogger(log.name, "job.lifecycle")
    try:
        raise ValueError("boom")
    except ValueError:
        ev.exception("failed", job_id="j2")
    entries, _ = buf.query(limit=50, after_id=None, min_level=None, q=None, logger_sub=None)
    assert len(entries) == 1
    assert entries[0]["level"] == "ERROR"
    assert entries[0]["job_id"] == "j2"
    assert entries[0]["exception"] is not None
    assert "ValueError" in (entries[0]["exception"] or "")
