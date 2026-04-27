from __future__ import annotations

import re

from app.jobs.schemas import JobRequest
from app.models import ModelName
from app.telegram.model_preferences import InMemoryModelPreferenceStore


class CommandParseError(ValueError):
    pass


class CommandParser:
    def __init__(
        self,
        default_project: str,
        default_model: ModelName,
        model_preferences: InMemoryModelPreferenceStore | None = None,
    ) -> None:
        self._default_project = default_project
        self._default_model = default_model
        self._model_preferences = model_preferences

    @staticmethod
    def _extract_options(text: str) -> tuple[ModelName | None, str | None, bool | None, str]:
        remaining = text
        model: ModelName | None = None
        branch: str | None = None
        commit: bool | None = None

        model_match = re.search(r"\bmodel:\s*(claude|codex)\b", remaining, flags=re.IGNORECASE)
        if model_match:
            model = ModelName(model_match.group(1).lower())
            remaining = re.sub(r"\bmodel:\s*(claude|codex)\b", "", remaining, flags=re.IGNORECASE).strip()

        branch_match = re.search(r"\bbranch:\s*([A-Za-z0-9._/\-]+)", remaining, flags=re.IGNORECASE)
        if branch_match:
            branch = branch_match.group(1)
            remaining = re.sub(r"\bbranch:\s*([A-Za-z0-9._/\-]+)", "", remaining, flags=re.IGNORECASE).strip()

        no_commit_match = re.search(r"\bno\s+commit\b", remaining, flags=re.IGNORECASE)
        if no_commit_match:
            commit = False
            remaining = re.sub(r"\bno\s+commit\b", "", remaining, flags=re.IGNORECASE).strip()

        return model, branch, commit, remaining

    def parse_natural(self, text: str, chat_id: int, user_id: int | None) -> JobRequest:
        model, branch, commit, instruction = self._extract_options(text.strip())
        if not instruction:
            raise CommandParseError("작업 지시문이 비어 있습니다.")
        selected_model = model
        if selected_model is None:
            if self._model_preferences is not None:
                selected_model = self._model_preferences.get(chat_id)
            else:
                selected_model = self._default_model
        return JobRequest(
            project=self._default_project,
            model=selected_model,
            instruction=instruction,
            branch=branch,
            commit=True if commit is None else commit,
            chat_id=chat_id,
            requested_by=user_id,
        )
