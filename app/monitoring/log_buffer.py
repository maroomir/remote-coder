"""관리 UI용 인메모리 로그 링 버퍼와 logging.Handler."""

from __future__ import annotations

import logging
import traceback
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import count
from threading import Lock
from typing import Any, Final

_LEVEL_ORDER: Final[dict[str, int]] = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}

LOG_RECORD_CONTEXT_KEYS: Final[tuple[str, ...]] = (
    "category",
    "chat_id",
    "user_id",
    "project",
    "job_id",
)


def _level_no(level_name: str) -> int | None:
    return _LEVEL_ORDER.get(level_name.upper())


def _context_from_dict(ctx: dict[str, Any] | None) -> dict[str, Any | None]:
    if not ctx:
        return {k: None for k in LOG_RECORD_CONTEXT_KEYS}
    out: dict[str, Any | None] = {}
    for k in LOG_RECORD_CONTEXT_KEYS:
        out[k] = ctx.get(k)
    return out


def _coerce_chat_or_user_id(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_category(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def _coerce_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


@dataclass(frozen=True)
class BufferedLogLine:
    id: int
    created_at: str
    level: str
    logger: str
    message: str
    exception: str | None
    category: str | None = None
    chat_id: int | None = None
    user_id: int | None = None
    project: str | None = None
    job_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "level": self.level,
            "logger": self.logger,
            "message": self.message,
            "exception": self.exception,
            "category": self.category,
            "chat_id": self.chat_id,
            "user_id": self.user_id,
            "project": self.project,
            "job_id": self.job_id,
        }


class InMemoryLogBuffer:
    """스레드 안전한 최근 로그 링 버퍼."""

    def __init__(self, max_entries: int = 2000) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be >= 1")
        self._max_entries = max_entries
        self._lock = Lock()
        self._lines: deque[BufferedLogLine] = deque(maxlen=max_entries)
        self._seq = count(1)

    @property
    def max_entries(self) -> int:
        return self._max_entries

    def push(
        self,
        *,
        level: str,
        logger_name: str,
        message: str,
        exception: str | None,
        context: dict[str, Any] | None = None,
    ) -> int:
        """한 줄을 추가하고 할당된 id를 반환합니다."""
        ctx = _context_from_dict(context)
        line_id = 0
        with self._lock:
            line_id = next(self._seq)
            created = datetime.now(UTC).isoformat().replace("+00:00", "Z")
            self._lines.append(
                BufferedLogLine(
                    id=line_id,
                    created_at=created,
                    level=level,
                    logger=logger_name,
                    message=message,
                    exception=exception,
                    category=_coerce_category(ctx.get("category")),
                    chat_id=_coerce_chat_or_user_id(ctx.get("chat_id")),
                    user_id=_coerce_chat_or_user_id(ctx.get("user_id")),
                    project=_coerce_str(ctx.get("project")),
                    job_id=_coerce_str(ctx.get("job_id")),
                )
            )
        return line_id

    def _snapshot(self) -> list[BufferedLogLine]:
        with self._lock:
            return list(self._lines)

    def max_id(self) -> int:
        with self._lock:
            if not self._lines:
                return 0
            return self._lines[-1].id

    def query(
        self,
        *,
        limit: int,
        after_id: int | None,
        min_level: str | None,
        q: str | None,
        logger_sub: str | None,
        chat_id: int | None = None,
        user_id: int | None = None,
        job_id: str | None = None,
        project: str | None = None,
        category: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """필터된 로그와 버퍼 내 최대 id를 반환합니다."""
        raw = self._snapshot()
        max_seen = raw[-1].id if raw else 0

        min_no: int | None = None
        if min_level:
            min_no = _level_no(min_level)
            if min_no is None:
                raise ValueError(f"unknown level: {min_level}")

        def passes(line: BufferedLogLine) -> bool:
            if after_id is not None and line.id <= after_id:
                return False
            if min_no is not None:
                ln = _level_no(line.level)
                if ln is None or ln < min_no:
                    return False
            if logger_sub and logger_sub.lower() not in line.logger.lower():
                return False
            if q:
                qq = q.lower()
                hay = line.message.lower()
                ex = (line.exception or "").lower()
                if qq not in hay and qq not in ex:
                    return False
            if chat_id is not None and line.chat_id != chat_id:
                return False
            if user_id is not None and line.user_id != user_id:
                return False
            if job_id is not None and (line.job_id is None or line.job_id != job_id):
                return False
            if project is not None and (line.project is None or line.project != project):
                return False
            if category is not None and (line.category is None or line.category != category):
                return False
            return True

        filtered = [line for line in raw if passes(line)]
        if after_id is None:
            window = filtered[-limit:] if len(filtered) > limit else filtered
        else:
            window = filtered[:limit]

        return [line.to_dict() for line in window], max_seen


class MemoryLogHandler(logging.Handler):
    """InMemoryLogBuffer로 레코드를 전달하는 logging.Handler."""

    def __init__(self, buffer: InMemoryLogBuffer) -> None:
        super().__init__(level=logging.DEBUG)
        self._buffer = buffer

    def emit(self, record: logging.LogRecord) -> None:
        try:
            exc_text: str | None = None
            if record.exc_info:
                exc_text = "".join(traceback.format_exception(*record.exc_info))
            context: dict[str, Any] = {}
            for k in LOG_RECORD_CONTEXT_KEYS:
                if hasattr(record, k):
                    context[k] = getattr(record, k)
            self._buffer.push(
                level=record.levelname,
                logger_name=record.name,
                message=record.getMessage(),
                exception=exc_text,
                context=context if context else None,
            )
        except Exception:  # pylint: disable=broad-except
            self.handleError(record)


def attach_app_memory_log_handler(
    buffer: InMemoryLogBuffer,
    *,
    app_logger_name: str = "app",
) -> MemoryLogHandler:
    """`app` 패키지 로거에 메모리 핸들러를 한 번만 붙입니다."""
    app_logger = logging.getLogger(app_logger_name)
    for h in app_logger.handlers:
        if getattr(h, "_remote_coder_admin_memory", False):
            return h  # type: ignore[return-value]
    handler = MemoryLogHandler(buffer)
    setattr(handler, "_remote_coder_admin_memory", True)
    app_logger.addHandler(handler)
    if app_logger.level == logging.NOTSET or app_logger.level > logging.INFO:
        app_logger.setLevel(logging.INFO)
    return handler
