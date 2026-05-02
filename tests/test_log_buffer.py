import logging

import pytest

from app.monitoring.log_buffer import InMemoryLogBuffer, MemoryLogHandler


def test_log_buffer_query_min_level_filters():
    buf = InMemoryLogBuffer(max_entries=100)
    buf.push(level="DEBUG", logger_name="x", message="d", exception=None)
    buf.push(level="INFO", logger_name="x", message="i", exception=None)
    entries, _ = buf.query(limit=50, after_id=None, min_level="INFO", q=None, logger_sub=None)
    assert len(entries) == 1
    assert entries[0]["level"] == "INFO"


def test_log_buffer_query_q_matches_exception():
    buf = InMemoryLogBuffer(max_entries=100)
    buf.push(level="ERROR", logger_name="x", message="fail", exception="ValueError: boom")
    entries, _ = buf.query(limit=50, after_id=None, min_level=None, q="boom", logger_sub=None)
    assert len(entries) == 1


def test_log_buffer_query_raises_on_unknown_level():
    buf = InMemoryLogBuffer(max_entries=100)
    with pytest.raises(ValueError, match="unknown level"):
        buf.query(limit=10, after_id=None, min_level="VERBOSE", q=None, logger_sub=None)


def test_push_preserves_context_and_query_filters():
    buf = InMemoryLogBuffer(max_entries=100)
    buf.push(
        level="INFO",
        logger_name="app.jobs",
        message="m",
        exception=None,
        context={"chat_id": 7, "job_id": "j1", "category": "job.lifecycle", "project": "p1"},
    )
    by_chat, _ = buf.query(limit=50, after_id=None, min_level=None, q=None, logger_sub=None, chat_id=7)
    assert len(by_chat) == 1
    assert by_chat[0]["chat_id"] == 7

    by_job, _ = buf.query(limit=50, after_id=None, min_level=None, q=None, logger_sub=None, job_id="j1")
    assert len(by_job) == 1
    assert by_job[0]["job_id"] == "j1"

    by_cat, _ = buf.query(
        limit=50, after_id=None, min_level=None, q=None, logger_sub=None, category="job.lifecycle"
    )
    assert len(by_cat) == 1
    assert by_cat[0]["category"] == "job.lifecycle"


def test_to_dict_includes_context_keys_even_when_none():
    buf = InMemoryLogBuffer(max_entries=10)
    buf.push(level="INFO", logger_name="x", message="hi", exception=None)
    entries, _ = buf.query(limit=10, after_id=None, min_level=None, q=None, logger_sub=None)
    assert len(entries) == 1
    d = entries[0]
    assert d["category"] is None
    assert d["chat_id"] is None
    assert d["user_id"] is None
    assert d["project"] is None
    assert d["job_id"] is None


def test_query_combines_chat_and_level_filters():
    buf = InMemoryLogBuffer(max_entries=100)
    buf.push(
        level="DEBUG",
        logger_name="x",
        message="a",
        exception=None,
        context={"chat_id": 1},
    )
    buf.push(
        level="INFO",
        logger_name="x",
        message="b",
        exception=None,
        context={"chat_id": 1},
    )
    buf.push(
        level="INFO",
        logger_name="x",
        message="c",
        exception=None,
        context={"chat_id": 2},
    )
    entries, _ = buf.query(
        limit=50, after_id=None, min_level="INFO", q=None, logger_sub=None, chat_id=1
    )
    assert len(entries) == 1
    assert entries[0]["message"] == "b"


def test_handler_emit_reads_extra_into_context():
    buf = InMemoryLogBuffer(max_entries=50)
    log = logging.getLogger("test_emit_ctx")
    log.handlers.clear()
    log.setLevel(logging.INFO)
    log.propagate = False
    log.addHandler(MemoryLogHandler(buf))
    log.info("hello", extra={"chat_id": 5, "category": "x", "evil": "nope"})
    entries, _ = buf.query(limit=50, after_id=None, min_level=None, q=None, logger_sub=None)
    assert len(entries) == 1
    assert entries[0]["message"] == "hello"
    assert entries[0]["chat_id"] == 5
    assert entries[0]["category"] == "x"
    assert "evil" not in entries[0]
