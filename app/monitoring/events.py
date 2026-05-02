"""도메인 이벤트를 구조화 컨텍스트와 함께 기록하는 Facade."""

from __future__ import annotations

import logging
from typing import Any

from app.monitoring.log_buffer import LOG_RECORD_CONTEXT_KEYS


class EventLogger:
    """`logging`의 `extra`에 허용된 컨텍스트 키만 넣고 category를 고정 주입합니다."""

    def __init__(self, logger_name: str, category: str) -> None:
        self._logger = logging.getLogger(logger_name)
        self._category = category

    def _extra(self, context: dict[str, Any]) -> dict[str, Any]:
        extra: dict[str, Any] = {"category": self._category}
        for k in LOG_RECORD_CONTEXT_KEYS:
            if k == "category":
                continue
            if k in context and context[k] is not None:
                extra[k] = context[k]
        return extra

    def info(self, message: str, *args: Any, **context: Any) -> None:
        self._logger.info(message, *args, extra=self._extra(context))

    def warning(self, message: str, *args: Any, **context: Any) -> None:
        self._logger.warning(message, *args, extra=self._extra(context))

    def error(self, message: str, *args: Any, **context: Any) -> None:
        self._logger.error(message, *args, extra=self._extra(context))

    def exception(self, message: str, *args: Any, **context: Any) -> None:
        self._logger.exception(message, *args, extra=self._extra(context))
