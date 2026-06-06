from __future__ import annotations

from app.monitoring.code import count_project_code, format_code_monitor
from app.monitoring.git import format_branch_monitor, format_worktree_monitor
from app.monitoring.memory import format_memory_monitor
from app.monitoring.model import format_model_monitor
from app.projects.registry import ProjectRecord
from app.telegram.commands.base import (
    CommandContext,
    InlineButton,
    TelegramCommand,
    TelegramMessage,
    _cmd_evt,
    effective_model_for_chat,
    effective_project_name_for_chat,
)

_VALID_SUBCOMMANDS = {"model", "memory", "branch", "worktrees", "code", "project"}


class MonitorCommand(TelegramCommand):
    name = "/monitor"
    description = "Check model, memory, branch, and worktree status"

    def execute(self, message: TelegramMessage, ctx: CommandContext) -> str:
        tokens = message.text.strip().split()
        if len(tokens) < 2:
            _cmd_evt.info("monitor usage requested", chat_id=message.chat_id, user_id=message.user_id)
            return "Choose a monitoring view."

        sub = tokens[1].lower()
        if sub not in _VALID_SUBCOMMANDS:
            _cmd_evt.warning(
                "monitor invalid subcommand sub=%s",
                sub,
                chat_id=message.chat_id,
                user_id=message.user_id,
            )
            return "Usage\n\n- /monitor <model|memory|branch|worktrees|code|project>\n- Example: /monitor memory"

        if sub == "project":
            return self._view_project(message, ctx)

        entry = self._resolve_enabled_project(message, ctx, sub)
        if isinstance(entry, str):
            return entry
        project_name = entry.name

        _cmd_evt.info(
            "monitor requested sub=%s",
            sub,
            chat_id=message.chat_id,
            user_id=message.user_id,
            project=project_name,
        )
        if sub == "model":
            return self._view_model(message, ctx, project_name)
        if sub == "memory":
            return self._view_memory(message, ctx, project_name)
        if sub == "branch":
            return format_branch_monitor(
                ctx.git_service, entry.root_path, ctx.git_remote_name, project_name
            )
        if sub == "worktrees":
            return format_worktree_monitor(
                ctx.git_service, entry.root_path, entry.worktree_base_dir, project_name
            )
        return self._view_code(message, ctx, entry, project_name)

    def _resolve_enabled_project(
        self, message: TelegramMessage, ctx: CommandContext, sub: str
    ) -> ProjectRecord | str:
        project_name = effective_project_name_for_chat(ctx, message.chat_id)
        if not project_name:
            _cmd_evt.warning(
                "monitor requested with no project sub=%s",
                sub,
                chat_id=message.chat_id,
                user_id=message.user_id,
            )
            return "No projects are registered. Register one at http://127.0.0.1:8000/projects."

        entry = ctx.project_registry.get(project_name)
        if not entry:
            _cmd_evt.warning(
                "monitor unknown project sub=%s",
                sub,
                chat_id=message.chat_id,
                user_id=message.user_id,
                project=project_name,
            )
            return f"Unknown project: {project_name}"
        if not entry.enabled:
            _cmd_evt.warning(
                "monitor disabled project sub=%s",
                sub,
                chat_id=message.chat_id,
                user_id=message.user_id,
                project=project_name,
            )
            return f"Disabled project: {project_name}"
        return entry

    def _view_project(self, message: TelegramMessage, ctx: CommandContext) -> str:
        effective = effective_project_name_for_chat(ctx, message.chat_id)
        if not effective:
            return "Could not find the project context for this bot."
        entry = ctx.project_registry.get(effective)
        if entry is None:
            return f"Unknown project: {effective}"
        _cmd_evt.info(
            "monitor project requested effective=%s",
            effective or "-",
            chat_id=message.chat_id,
            user_id=message.user_id,
            project=effective,
        )
        state = "on" if entry.enabled else "off"
        return "\n".join(
            [
                f"This bot project: {entry.name}",
                f"Status: {state}",
                f"root_path: {entry.root_path}",
                f"default_model: {entry.default_model.value}",
                f"worktree_base_dir: {entry.worktree_base_dir}",
            ]
        )

    def _view_model(self, message: TelegramMessage, ctx: CommandContext, project_name: str) -> str:
        current = effective_model_for_chat(ctx, message.chat_id, project_name)
        body = format_model_monitor(
            current,
            recent_jobs=ctx.job_store.list_recent_for_project_chat(
                project_name, message.chat_id, 50
            ),
            chat_id=message.chat_id,
            project=project_name,
        )
        return f"Current chat default model: {current.value}\n\n{body}"

    def _view_memory(self, message: TelegramMessage, ctx: CommandContext, project_name: str) -> str:
        if ctx.conversation_store is None:
            return "Conversation memory store is not configured."
        stats = ctx.conversation_store.get_chat_stats(project_name, message.chat_id)
        return format_memory_monitor(stats, project_name, message.chat_id)

    def _view_code(
        self, message: TelegramMessage, ctx: CommandContext, entry: ProjectRecord, project_name: str
    ) -> str:
        stats = count_project_code(
            entry.root_path,
            worktree_base_dir=entry.worktree_base_dir,
        )
        _cmd_evt.info(
            "monitor code counted files=%d lines=%d skipped=%d",
            stats.files_scanned,
            stats.total_lines,
            stats.skipped_binary_or_error,
            chat_id=message.chat_id,
            user_id=message.user_id,
            project=project_name,
        )
        return format_code_monitor(stats, project_name, entry.root_path)

    def get_inline_buttons(
        self,
        message: TelegramMessage | None = None,
        ctx: CommandContext | None = None,
    ) -> list[list[InlineButton]] | None:
        _ = ctx
        tokens = message.text.strip().split() if message is not None else []
        if len(tokens) != 1:
            return None
        return [
            [
                InlineButton("model", "/monitor model"),
                InlineButton("memory", "/monitor memory"),
                InlineButton("branch", "/monitor branch"),
            ],
            [
                InlineButton("worktrees", "/monitor worktrees"),
                InlineButton("code", "/monitor code"),
                InlineButton("project", "/monitor project"),
            ],
        ]
