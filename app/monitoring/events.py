from __future__ import annotations

import logging
from typing import Any

from app.monitoring.log_buffer import LOG_RECORD_CONTEXT_KEYS


class EventLogger:
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
