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
from app.telegram.lists import render_command_list

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


MODEL_USAGE = "<claude|codex|gemini|ollama>"


@dataclass
class InlineButton:
    label: str
    callback_data: str
    style: str | None = None


@dataclass
class CommandResponse:
    text: str
    inline_buttons: list[list["InlineButton"]] | None = None
    skip_notifier_body_i18n: bool = False
    prefer_edit: bool = False


def _help_response_skips_notifier_body_i18n(message_text: str) -> bool:
    _ = message_text
    return False


_HELP_COMMAND_ROWS: tuple[tuple[str, str, str], ...] = (
    ("/model", "<claude|codex|gemini|ollama>", "Change the default model"),
    ("/status", "<job_id>", "Check job status"),
    ("/log", "<job_id>", "Show job AI output logs"),
    ("/branch", "[name]", "Show or switch branches"),
    ("/pull", "", "Pull remote branch updates"),
    ("/rebase", "[branch]", "Rebase a branch"),
    ("/pr", "[branch]", "Open a GitHub PR"),
    ("/monitor", "<scope>", "Monitoring"),
    ("/clear", "<branch|worktrees|memory>", "Cleanup (confirmation)"),
    ("/reports", "[count]", "Conversation memory report"),
    ("/init", "", "Reset this chat's settings"),
    ("/stop", "<job_id>", "Stop a running job"),
    ("/fix", "", "Fix linked job commit"),
    ("/start", "", "Inline menu"),
)


HELP_TEXT = "\n".join(
    [
        "🧭 Help",
        "",
        "Send work requests as regular messages.",
        "",
        "⚙️ Options",
        "- model:",
        "- branch:",
        "- no commit",
        "- plan: <natural language> or /plan <natural language> - plan mode (plan only; no code changes)",
        "- ask: <natural language> or /ask <natural language> - ask mode (analysis and answers; no code edits)",
        "- research: <natural language> or /research <natural language> - research mode (internet-backed answers; no code edits)",
        "- fix: <natural language> or /fix - fix mode (reply to a job result; amends that commit)",
        "- Korean aliases 계획:, 질문:, 조사:, and 수정: instead of plan:/ask:/research:/fix: (colons `:` or full-width `：` allowed)",
        "",
        "📋 Commands",
        render_command_list(_HELP_COMMAND_ROWS),
        "",
        "💡 Tip: Reply to a job result and send `fix: ...` to amend that commit.",
    ]
)

HELP_AGENT_TOPIC = "\n".join(
    [
        "🤖 AGENTS mode (agent)",
        "",
        "Natural-language coding tasks. The agent can modify code in the current project; when there are "
        "changes it can create or update a branch, commit, and push.",
        "",
        "💡 Examples",
        "- fix the login validation bug",
        "- model: codex branch: remote-auth strengthen tests",
        "- no commit just verify the doc wording",
        "",
        "A job is accepted after project/branch/model checks with inline Yes/No buttons.",
    ]
)

HELP_PLAN_TOPIC = "\n".join(
    [
        "📐 Plan mode (plan)",
        "",
        "Receive change plans only; no code edits. Like agent mode, a job is accepted after confirmation "
        "with inline Yes/No buttons.",
        "",
        "💡 Examples",
        "- plan: summarize the login validation flow",
        "- /plan model: codex list only API boundary risks",
        "- 계획：refactor steps (full-width colon)",
        "",
        "See /help for more options.",
    ]
)

HELP_ASK_TOPIC = "\n".join(
    [
        "❓ Ask mode (ask)",
        "",
        "Answer questions using the repository; no code edits, commits, or pushes. Jobs are accepted like "
        "agent mode after confirmation with inline Yes/No buttons.",
        "",
        "💡 Examples",
        "- ask: how do I run pytest in this project?",
        "- /ask explain JobManager.run stages",
        "- 질문：what this error line means",
        "",
        "See /help for more options.",
    ]
)

HELP_RESEARCH_TOPIC = "\n".join(
    [
        "🔎 Research mode (research)",
        "",
        "Answer research questions using repository context and internet search when useful; no code edits, "
        "commits, or pushes. Jobs are accepted like agent mode after confirmation with inline Yes/No buttons.",
        "",
        "💡 Examples",
        "- research: compare webhook retry strategies for this service",
        "- /research model: codex find current FastAPI deployment guidance",
        "- 조사：Telegram webhook 보안 권장사항 조사",
        "",
        "See /help for more options.",
    ]
)

HELP_FIX_TOPIC = "\n".join(
    [
        "🔧 Fix mode (fix)",
        "",
        "Apply follow-up fixes on top of a previous succeeded job. Reply to a job result, then use "
        "fix: or /fix. The agent amends the existing commit and pushes with --force-with-lease.",
        "",
        "💡 Examples",
        "- (reply to job result) fix: add missing tests",
        "- (reply to job result) /fix then send the fix instruction",
        "- (reply to job result) 수정：로그인 검증 버그도 고쳐줘",
        "",
        "See /help for more options.",
    ]
)


def _button_rows(buttons: list[InlineButton], per_row: int = 2) -> list[list[InlineButton]]:
    return [buttons[i : i + per_row] for i in range(0, len(buttons), per_row)]


NAV_CLOSE_CALLBACK = "__close__"


def with_nav_row(
    rows: list[list[InlineButton]] | None,
    *,
    back_to: str | None = None,
    closeable: bool = True,
) -> list[list[InlineButton]]:
    """Append a standard navigation row (‹ Back / ✖ Close) to a keyboard.

    ``back_to`` is the parent view's command string (stateless; reconstructed on
    the next callback). ``closeable`` adds a Close button that collapses the panel.
    """
    result = [list(row) for row in (rows or [])]
    nav: list[InlineButton] = []
    if back_to is not None:
        nav.append(InlineButton("‹ Back", back_to))
    if closeable:
        nav.append(InlineButton("✖ Close", NAV_CLOSE_CALLBACK))
    if nav:
        result.append(nav)
    return result


def _job_button_label(job: Job) -> str:
    return f"{job.id} ({job.status.value})"


def effective_git_remote_name(ctx: CommandContext) -> str:
    if ctx.advanced_settings_store is not None:
        return ctx.advanced_settings_store.get().git_remote_name
    return ctx.git_remote_name


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
