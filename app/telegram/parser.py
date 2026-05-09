from __future__ import annotations

import re

from app.git.service import GitWorktreeService
from app.jobs.schemas import JobRequest
from app.models import ModelName
from app.projects.registry import ProjectRegistry
from app.telegram.conversation import (
    ConversationContextBuilder,
    SQLiteConversationStore,
    is_ambiguous_followup,
)
from app.telegram.model_preferences import InMemoryModelPreferenceStore


class CommandParseError(ValueError):
    pass


_MODEL_OPTION_PATTERN = "|".join(model.value for model in ModelName)


class CommandParser:
    def __init__(
        self,
        project_registry: ProjectRegistry,
        default_model: ModelName,
        model_preferences: InMemoryModelPreferenceStore | None = None,
        conversation_store: SQLiteConversationStore | None = None,
        conversation_recent_limit: int = 10,
    ) -> None:
        self._project_registry = project_registry
        self._default_model = default_model
        self._model_preferences = model_preferences
        self._conversation_store = conversation_store
        self._conversation_recent_limit = conversation_recent_limit

    @staticmethod
    def _extract_options(
        text: str,
    ) -> tuple[ModelName | None, str | None, bool | None, str]:
        remaining = text
        model: ModelName | None = None
        branch: str | None = None
        commit: bool | None = None

        model_match = re.search(
            rf"\bmodel:\s*({_MODEL_OPTION_PATTERN})\b",
            remaining,
            flags=re.IGNORECASE,
        )
        if model_match:
            model = ModelName(model_match.group(1).lower())
            remaining = re.sub(
                rf"\bmodel:\s*({_MODEL_OPTION_PATTERN})\b",
                "",
                remaining,
                flags=re.IGNORECASE,
            ).strip()

        branch_match = re.search(r"\bbranch:\s*([A-Za-z0-9._/\-]+)", remaining, flags=re.IGNORECASE)
        if branch_match:
            branch = branch_match.group(1)
            remaining = re.sub(r"\bbranch:\s*([A-Za-z0-9._/\-]+)", "", remaining, flags=re.IGNORECASE).strip()

        no_commit_match = re.search(r"\bno\s+commit\b", remaining, flags=re.IGNORECASE)
        if no_commit_match:
            commit = False
            remaining = re.sub(r"\bno\s+commit\b", "", remaining, flags=re.IGNORECASE).strip()

        return model, branch, commit, remaining

    def parse_natural(
        self,
        text: str,
        project_name: str,
        chat_id: int,
        user_id: int | None,
        message_id: int | None = None,
        reply_to_message_id: int | None = None,
        reply_to_text: str | None = None,
    ) -> JobRequest:
        model, branch, commit, remaining = self._extract_options(text.strip())
        if not remaining:
            raise CommandParseError("작업 지시문이 비어 있습니다.")

        entry = self._project_registry.get(project_name)
        if not entry:
            raise CommandParseError(f"알 수 없는 프로젝트: {project_name}")
        if not entry.enabled:
            raise CommandParseError(f"비활성화된 프로젝트: {project_name}")

        selected_model: ModelName
        if model is not None:
            selected_model = model
        elif self._model_preferences is not None:
            selected_model = self._model_preferences.get_explicit(project_name, chat_id) or entry.default_model
        else:
            selected_model = entry.default_model

        if (
            branch is None
            and reply_to_message_id is not None
            and self._conversation_store is not None
        ):
            branch = self._conversation_store.get_bound_branch(
                project_name,
                chat_id,
                reply_to_message_id,
            )

        if branch is not None:
            branch_err = GitWorktreeService.validate_branch_token(branch)
            if branch_err:
                raise CommandParseError(branch_err)

        instruction_body = remaining.strip()
        reply_prefix = ""
        if reply_to_message_id is not None and self._conversation_store is not None:
            reply_prefix = self._conversation_store.format_reply_chain_context(
                project_name,
                chat_id,
                reply_to_message_id,
            ).strip()
        if not reply_prefix and reply_to_message_id is not None and reply_to_text:
            reply_prefix = "\n".join(
                [
                    "[Reply 메시지 맥락]",
                    f"message_id={reply_to_message_id}:",
                    f"  text: {reply_to_text.strip()}",
                    "[/Reply 메시지 맥락]",
                ]
            )

        chain_message_ids: set[int] = set()
        if reply_to_message_id is not None and self._conversation_store is not None:
            chain_message_ids = self._conversation_store.collect_reply_chain_message_ids(
                project_name,
                chat_id,
                reply_to_message_id,
            )

        if is_ambiguous_followup(instruction_body) and self._conversation_store is not None:
            entries = self._conversation_store.list_recent(
                project_name,
                chat_id,
                self._conversation_recent_limit,
            )
            filtered = [
                e
                for e in entries
                if e.message_id is None or e.message_id not in chain_message_ids
            ]
            if not filtered:
                if not reply_prefix:
                    raise CommandParseError(
                        "이전 작업 맥락이 없습니다. 구체적인 작업 지시를 보내주세요.",
                    )
                instruction = f"{reply_prefix}\n\n{instruction_body}".strip()
            else:
                inner = ConversationContextBuilder.build(filtered, instruction_body)
                instruction = f"{reply_prefix}\n\n{inner}".strip() if reply_prefix else inner
        elif reply_prefix:
            instruction = f"{reply_prefix}\n\n{instruction_body}".strip()
        else:
            instruction = instruction_body

        return JobRequest(
            project=project_name,
            model=selected_model,
            instruction=instruction,
            branch=branch,
            commit=True if commit is None else commit,
            chat_id=chat_id,
            requested_by=user_id,
            message_id=message_id,
            reply_to_message_id=reply_to_message_id,
        )
