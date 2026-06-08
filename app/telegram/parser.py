from __future__ import annotations

import re

from app.git.service import GitWorktreeService
from app.jobs.schemas import JobMode, JobRequest
from app.models import ModelName
from app.projects.registry import ProjectRegistry
from app.telegram.conversation import (
    ConversationContextBuilder,
    SQLiteConversationStore,
    is_ambiguous_followup,
)
from app.telegram.i18n import (
    command_parse_error_disabled_project,
    command_parse_error_empty_instruction,
    command_parse_error_empty_instruction_plan_ask,
    command_parse_error_no_previous_job_context,
    command_parse_error_unknown_project,
    instruction_frame_labels,
    language_from_settings_store,
    localize_git_branch_validation_message,
)
from app.telegram.model_preferences import InMemoryModelPreferenceStore, ModelPreference


class CommandParseError(ValueError):
    pass


_MODEL_OPTION_PATTERN = "|".join(model.value for model in ModelName)

_SLASH_PLAN_ASK = re.compile(r"^/(plan|ask)\b\s*", re.IGNORECASE)
_PREFIX_PLAN_ASK = re.compile(
    r"^(plan|ask|계획|질문)\s*[:：]\s*",
    re.IGNORECASE,
)
_REPLY_JOB_ID_PATTERN = re.compile(
    r"\bJob ID:\s*`?([A-Za-z0-9_.:-]+)`?",
    re.IGNORECASE,
)


def _job_mode_from_plan_ask_keyword(key: str) -> JobMode:
    lowered = key.lower()
    if lowered in ("plan", "계획"):
        return JobMode.PLAN
    if lowered in ("ask", "질문"):
        return JobMode.ASK
    raise AssertionError(key)


def _extract_reply_job_id(text: str) -> str | None:
    match = _REPLY_JOB_ID_PATTERN.search(text)
    return match.group(1) if match else None


class CommandParser:
    def __init__(
        self,
        project_registry: ProjectRegistry,
        default_model: ModelName,
        model_preferences: InMemoryModelPreferenceStore | None = None,
        conversation_store: SQLiteConversationStore | None = None,
        conversation_recent_limit: int = 10,
        advanced_settings_store=None,
    ) -> None:
        self._project_registry = project_registry
        self._default_model = default_model
        self._model_preferences = model_preferences
        self._conversation_store = conversation_store
        self._conversation_recent_limit = conversation_recent_limit
        self._advanced_settings_store = advanced_settings_store

    def _effective_conversation_recent_limit(self) -> int:
        if self._advanced_settings_store is not None:
            return self._advanced_settings_store.get().conversation_recent_limit
        return self._conversation_recent_limit

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

    @staticmethod
    def _strip_leading_job_mode(text: str) -> tuple[JobMode, str]:
        stripped = text.strip()
        slash = _SLASH_PLAN_ASK.match(stripped)
        if slash:
            key = slash.group(1).lower()
            mode = JobMode.PLAN if key == "plan" else JobMode.ASK
            return mode, stripped[slash.end() :].strip()
        prefix = _PREFIX_PLAN_ASK.match(stripped)
        if prefix:
            mode = _job_mode_from_plan_ask_keyword(prefix.group(1))
            return mode, stripped[prefix.end() :].strip()
        return JobMode.AGENT, stripped

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
        lang = language_from_settings_store(self._advanced_settings_store)
        mode, stripped = self._strip_leading_job_mode(text)

        model, branch, commit, remaining = self._extract_options(stripped)
        if mode in (JobMode.PLAN, JobMode.ASK):
            branch = None
            commit = False

        if not remaining:
            if mode in (JobMode.PLAN, JobMode.ASK):
                raise CommandParseError(command_parse_error_empty_instruction_plan_ask(lang))
            raise CommandParseError(command_parse_error_empty_instruction(lang))

        entry = self._project_registry.get(project_name)
        if not entry:
            raise CommandParseError(command_parse_error_unknown_project(project_name, lang))
        if not entry.enabled:
            raise CommandParseError(command_parse_error_disabled_project(project_name, lang))

        selected_model: ModelName
        selected_model_id: str | None = None
        if model is not None:
            selected_model = model
        elif self._model_preferences is not None:
            selection = self._model_preferences.get_explicit_selection(project_name, chat_id)
            if selection is None:
                selection = ModelPreference(entry.default_model)
            selected_model = selection.provider
            selected_model_id = selection.model_id
        else:
            selected_model = entry.default_model

        if (
            mode == JobMode.AGENT
            and branch is None
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
                raise CommandParseError(localize_git_branch_validation_message(branch_err, lang))

        instruction_body = remaining.strip()
        reply_prefix = ""
        if reply_to_message_id is not None and self._conversation_store is not None:
            reply_prefix = self._conversation_store.format_reply_context(
                project_name,
                chat_id,
                reply_to_message_id,
                lang,
            ).strip()
        if not reply_prefix and reply_to_message_id is not None and reply_to_text:
            frame = instruction_frame_labels(lang)
            if self._conversation_store is not None:
                extracted_reply_job_id = _extract_reply_job_id(reply_to_text)
                if extracted_reply_job_id:
                    reply_prefix = self._conversation_store.format_job_context(
                        project_name,
                        chat_id,
                        extracted_reply_job_id,
                        lang,
                    ).strip()
            if not reply_prefix:
                reply_prefix = "\n".join(
                    [
                        frame.reply_message_open,
                        f"message_id={reply_to_message_id}:",
                        f"  text: {reply_to_text.strip()}",
                        frame.reply_message_close,
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
                self._effective_conversation_recent_limit(),
            )
            filtered = [
                e
                for e in entries
                if e.message_id is None or e.message_id not in chain_message_ids
            ]
            if not filtered:
                if not reply_prefix:
                    raise CommandParseError(command_parse_error_no_previous_job_context(lang))
                instruction = f"{reply_prefix}\n\n{instruction_body}".strip()
            else:
                inner = ConversationContextBuilder.build(filtered, instruction_body, lang)
                instruction = f"{reply_prefix}\n\n{inner}".strip() if reply_prefix else inner
        elif reply_prefix:
            instruction = f"{reply_prefix}\n\n{instruction_body}".strip()
        else:
            instruction = instruction_body

        effective_commit = False if mode in (JobMode.PLAN, JobMode.ASK) else (True if commit is None else commit)

        return JobRequest(
            project=project_name,
            model=selected_model,
            model_id=selected_model_id,
            instruction=instruction,
            mode=mode,
            branch=branch,
            commit=effective_commit,
            chat_id=chat_id,
            requested_by=user_id,
            message_id=message_id,
            reply_to_message_id=reply_to_message_id,
        )
