import pytest

from app.monitoring.log_buffer import InMemoryLogBuffer


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
