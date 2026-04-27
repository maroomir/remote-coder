from __future__ import annotations

from app.jobs.schemas import JobRequest
from app.models import ModelName


class CommandParseError(ValueError):
    pass


class CommandParser:
    def __init__(self, default_project: str, default_model: ModelName) -> None:
        self._default_project = default_project
        self._default_model = default_model

    def parse_natural(self, text: str, chat_id: int, user_id: int | None) -> JobRequest:
        instruction = text.strip()
        if not instruction:
            raise CommandParseError("작업 지시문이 비어 있습니다.")
        return JobRequest(
            project=self._default_project,
            model=self._default_model,
            instruction=instruction,
            chat_id=chat_id,
            requested_by=user_id,
        )
