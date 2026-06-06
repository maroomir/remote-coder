from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.jobs.schemas import Job
from app.jobs.store import JobStore
from app.models import ModelName
from app.monitoring.events import EventLogger
from app.projects.registry import ProjectRegistry
from app.telegram.confirmations import InMemoryConfirmationStore, PendingConfirmation
from app.telegram.conversation import SQLiteConversationStore
from app.telegram.model_preferences import InMemoryModelPreferenceStore, ModelPreference

if TYPE_CHECKING:
    from app.admin.advanced_settings import FileAdvancedSettingsStore
    from app.git.service import GitWorktreeService
    from app.jobs.manager import JobManager

_cmd_evt = EventLogger("app.telegram.command", "telegram.command")


@dataclass
class TelegramMessage:
    chat_id: int
    user_id: int | None
    text: str


@dataclass
class CommandContext:
    job_store: JobStore
    default_model: ModelName
    project_registry: ProjectRegistry
    model_preferences: InMemoryModelPreferenceStore
    project_name: str | None
    git_service: GitWorktreeService
    git_remote_name: str
    confirmation_store: InMemoryConfirmationStore
    conversation_store: SQLiteConversationStore | None = None
    job_manager: JobManager | None = None
    advanced_settings_store: FileAdvancedSettingsStore | None = None


def format_usage(*lines: str) -> str:
    return "Usage\n\n" + "\n".join(f"- {line}" for line in lines)


MODEL_USAGE = "<claude|codex|gemini>"


@dataclass
class InlineButton:
    label: str
    callback_data: str


@dataclass
class CommandResponse:
    text: str
    inline_buttons: list[list["InlineButton"]] | None = None
    skip_notifier_body_i18n: bool = False


def _help_response_skips_notifier_body_i18n(message_text: str) -> bool:
    _ = message_text
    return False


HELP_TEXT = "\n".join(
    [
        "Help",
        "",
        "Send work requests as regular messages.",
        "",
        "Options",
        "- model:",
        "- branch:",
        "- no commit",
        "- plan: <natural language> or /plan <natural language> - plan mode (plan only; no code changes)",
        "- ask: <natural language> or /ask <natural language> - ask mode (analysis and answers; no code edits)",
        "- Korean aliases 계획: and 질문: instead of plan:/ask: (colons `:` or full-width `：` allowed)",
        "",
        "Commands:",
        "- /model <claude|codex|gemini>: Change the default model",
        "- /status <job_id>: Check job status",
        "- /branch [name]: Show or switch branches",
        "- /pull: Pull all remote branch updates",
        "- /rebase [branch]: Rebase a branch",
        "- /pr [branch]: Open a GitHub PR for a branch",
        "- /monitor <model|memory|branch|worktrees|code|project>: Monitoring",
        "- /clear <branch|worktrees|memory>: Cleanup (confirmation required)",
        "- /reports [count]: Conversation memory report",
        "- /init: Reset this chat's settings",
        "- /stop <job_id>: Stop a running job",
        "- /fix <commit|source> [job_id]: Re-do a job's commit/source (amend + force-with-lease push)",
        "- /start: Inline menu",
    ]
)

HELP_AGENT_TOPIC = "\n".join(
    [
        "AGENTS mode (agent)",
        "",
        "Natural-language coding tasks. The agent can modify code in the current project; when there are "
        "changes it can create or update a branch, commit, and push.",
        "",
        "Examples",
        "- fix the login validation bug",
        "- model: codex branch: remote-auth strengthen tests",
        "- no commit just verify the doc wording",
        "",
        "A job is accepted after project/branch/model checks via `y`/`Y` or inline buttons.",
    ]
)

HELP_PLAN_TOPIC = "\n".join(
    [
        "Plan mode (plan)",
        "",
        "Receive change plans only; no code edits. Like agent mode, a job is accepted after confirmation "
        "(`y`/`Y` or inline buttons).",
        "",
        "Examples",
        "- plan: summarize the login validation flow",
        "- /plan model: codex list only API boundary risks",
        "- 계획：refactor steps (full-width colon)",
        "",
        "See /help for more options.",
    ]
)

HELP_ASK_TOPIC = "\n".join(
    [
        "Ask mode (ask)",
        "",
        "Answer questions using the repository; no code edits, commits, or pushes. Jobs are accepted like "
        "agent mode after confirmation (`y`/`Y` or inline buttons).",
        "",
        "Examples",
        "- ask: how do I run pytest in this project?",
        "- /ask explain JobManager.run stages",
        "- 질문：what this error line means",
        "",
        "See /help for more options.",
    ]
)


def _button_rows(buttons: list[InlineButton], per_row: int = 2) -> list[list[InlineButton]]:
    return [buttons[i : i + per_row] for i in range(0, len(buttons), per_row)]


def _job_button_label(job: Job) -> str:
    return f"{job.id} ({job.status.value})"


def _confirmation_buttons_enabled(ctx: CommandContext) -> bool:
    if ctx.advanced_settings_store is None:
        return False
    return ctx.advanced_settings_store.get().natural_job_confirmation_buttons_enabled


def effective_project_name_for_chat(ctx: CommandContext, chat_id: int) -> str | None:
    _ = chat_id
    return ctx.project_name


def effective_model_for_chat(ctx: CommandContext, chat_id: int, project_name: str | None) -> ModelName:
    explicit = ctx.model_preferences.get_explicit(project_name, chat_id)
    if explicit is not None:
        return explicit
    if project_name:
        entry = ctx.project_registry.get(project_name)
        if entry is not None:
            return entry.default_model
    return ctx.default_model


def effective_model_selection_for_chat(
    ctx: CommandContext,
    chat_id: int,
    project_name: str | None,
) -> ModelPreference:
    explicit = ctx.model_preferences.get_explicit_selection(project_name, chat_id)
    if explicit is not None:
        return explicit
    if project_name:
        entry = ctx.project_registry.get(project_name)
        if entry is not None:
            return ModelPreference(entry.default_model)
    return ModelPreference(ctx.default_model)


class TelegramCommand(ABC):
    name: str
    menu_text: str | None = None
    description: str | None = None

    @abstractmethod
    def execute(self, message: TelegramMessage, ctx: CommandContext) -> str:
        raise NotImplementedError

    def get_inline_buttons(
        self,
        message: TelegramMessage | None = None,
        ctx: CommandContext | None = None,
    ) -> list[list[InlineButton]] | None:
        _ = (message, ctx)
        return None


class ConfirmableCommand(TelegramCommand):
    @abstractmethod
    def confirm(
        self,
        message: TelegramMessage,
        ctx: CommandContext,
        pending: PendingConfirmation,
    ) -> str:
        raise NotImplementedError
