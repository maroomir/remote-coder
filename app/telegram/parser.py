from __future__ import annotations

import re

from app.jobs.schemas import JobRequest
from app.models import ModelName
from app.projects.registry import ProjectRegistry
from app.telegram.model_preferences import InMemoryModelPreferenceStore
from app.telegram.project_preferences import InMemoryProjectPreferenceStore


class CommandParseError(ValueError):
    pass


class CommandParser:
    def __init__(
        self,
        project_registry: ProjectRegistry,
        default_model: ModelName,
        model_preferences: InMemoryModelPreferenceStore | None = None,
        project_preferences: InMemoryProjectPreferenceStore | None = None,
    ) -> None:
        self._project_registry = project_registry
        self._default_model = default_model
        self._model_preferences = model_preferences
        self._project_preferences = project_preferences

    @staticmethod
    def _extract_options(
        text: str,
    ) -> tuple[ModelName | None, str | None, bool | None, str | None, str]:
        remaining = text
        model: ModelName | None = None
        branch: str | None = None
        commit: bool | None = None
        project: str | None = None

        project_match = re.search(
            r"\bproject:\s*([A-Za-z0-9][A-Za-z0-9._-]*)\b",
            remaining,
            flags=re.IGNORECASE,
        )
        if project_match:
            project = project_match.group(1)
            remaining = re.sub(
                r"\bproject:\s*[A-Za-z0-9][A-Za-z0-9._-]*\b",
                "",
                remaining,
                flags=re.IGNORECASE,
            ).strip()

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

        return model, branch, commit, project, remaining

    def parse_natural(self, text: str, chat_id: int, user_id: int | None) -> JobRequest:
        model, branch, commit, project_slug, instruction = self._extract_options(text.strip())
        if not instruction:
            raise CommandParseError("작업 지시문이 비어 있습니다.")

        default_name = self._project_registry.get_default_project_name()
        if not default_name:
            raise CommandParseError(
                "등록된 기본 프로젝트가 없습니다. 브라우저에서 http://127.0.0.1:8000/ 로 프로젝트를 등록하세요.",
            )

        chat_pref = (
            self._project_preferences.get(chat_id) if self._project_preferences is not None else None
        )
        project_name = project_slug or chat_pref or default_name
        entry = self._project_registry.get(project_name)
        if not entry:
            raise CommandParseError(f"알 수 없는 프로젝트: {project_name}")
        if not entry.enabled:
            raise CommandParseError(f"비활성화된 프로젝트: {project_name}")

        selected_model: ModelName
        if model is not None:
            selected_model = model
        elif self._model_preferences is not None:
            selected_model = self._model_preferences.get(chat_id)
        else:
            selected_model = entry.default_model

        return JobRequest(
            project=project_name,
            model=selected_model,
            instruction=instruction,
            branch=branch,
            commit=True if commit is None else commit,
            chat_id=chat_id,
            requested_by=user_id,
        )
