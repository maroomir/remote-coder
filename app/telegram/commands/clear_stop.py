from __future__ import annotations

from app.jobs.schemas import Job, JobStatus
from app.projects.registry import ProjectRecord
from app.telegram.commands.base import (
    CommandContext,
    ConfirmableCommand,
    InlineButton,
    TelegramCommand,
    TelegramMessage,
    _button_rows,
    _cmd_evt,
    _job_button_label,
    effective_git_remote_name,
    effective_project_name_for_chat,
)
from app.telegram.confirmations import PendingConfirmation

CLEAR_CONFIRM_YES = "__clear_confirm__:yes"
CLEAR_CONFIRM_NO = "__clear_confirm__:no"


class ClearCommand(ConfirmableCommand):
    name = "/clear"
    description = "Clean branches, worktrees, or conversation memory after confirmation"

    def execute(self, message: TelegramMessage, ctx: CommandContext) -> str:
        tokens = message.text.strip().split()
        if len(tokens) == 1:
            return "Choose what to clear. A confirmation button is required before running."
        if len(tokens) != 2 or tokens[1] not in {"branch", "memory", "worktrees"}:
            return "Usage: /clear branch or /clear worktrees or /clear memory"

        action = tokens[1]
        if action == "memory" and ctx.conversation_store is None:
            return "Memory store is not configured."

        ctx.confirmation_store.set(
            effective_project_name_for_chat(ctx, message.chat_id),
            message.chat_id,
            PendingConfirmation(command_name=self.name, action=action),
        )

        if action == "branch":
            summary = "Delete remote-* branches and their linked worktrees in this bot project."
        elif action == "worktrees":
            summary = "Clean managed worktrees and prune stale entries in this bot project."
        else:
            summary = "Delete only this chat's conversation memory in this bot project."
        return f"Pending action: {summary}\nChoose whether to run it."

    def get_inline_buttons(
        self,
        message: TelegramMessage | None = None,
        ctx: CommandContext | None = None,
    ) -> list[list[InlineButton]] | None:
        if message is None or ctx is None:
            return None
        tokens = message.text.strip().split()
        if len(tokens) == 1:
            return [
                [
                    InlineButton("branch", "/clear branch"),
                    InlineButton("worktrees", "/clear worktrees"),
                    InlineButton("memory", "/clear memory"),
                ],
            ]
        pending = ctx.confirmation_store.get(
            effective_project_name_for_chat(ctx, message.chat_id),
            message.chat_id,
        )
        if pending is None or pending.command_name != self.name:
            return None
        return [[InlineButton("Yes", CLEAR_CONFIRM_YES), InlineButton("No", CLEAR_CONFIRM_NO)]]

    def confirm(
        self,
        message: TelegramMessage,
        ctx: CommandContext,
        pending: PendingConfirmation,
    ) -> str:
        if message.text.strip() != CLEAR_CONFIRM_YES:
            if pending.action == "branch":
                target = "Branch cleanup"
            elif pending.action == "worktrees":
                target = "Worktree cleanup"
            else:
                target = "Memory cleanup"
            return f"{target} was cancelled."

        _cmd_evt.info("clear confirmed action=%s", pending.action, chat_id=message.chat_id)
        if pending.action == "branch":
            return self._clear_branches(ctx)
        if pending.action == "worktrees":
            return self._clear_worktrees(ctx)
        if pending.action == "memory":
            return self._clear_memory(ctx, message.chat_id)
        return "Unknown clear action."

    def _bound_project_record(self, ctx: CommandContext) -> ProjectRecord | None:
        name = ctx.project_name
        if not name:
            return None
        return ctx.project_registry.get(name)

    def _clear_branches(self, ctx: CommandContext) -> str:
        p = self._bound_project_record(ctx)
        if p is None:
            return "No project is bound to this bot or the project was not found in the registry."
        if not p.enabled:
            return f"Project is disabled: {p.name}"

        try:
            ctx.git_service.checkout_integrate_branch(p.root_path)
            remote_branches = ctx.git_service.list_remote_branches_matching(
                p.root_path, effective_git_remote_name(ctx), "remote-"
            )
            local_branches = ctx.git_service.list_local_branches_matching(p.root_path, "remote-")
            if remote_branches:
                ctx.git_service.delete_remote_branches(p.root_path, effective_git_remote_name(ctx), remote_branches)
            if local_branches:
                ctx.git_service.remove_linked_worktrees_for_branches(p.root_path, local_branches)
                ctx.git_service.delete_local_branches(p.root_path, local_branches)
            return (
                f"{p.name}: remote {len(remote_branches)}, local {len(local_branches)} deleted "
                f"({effective_git_remote_name(ctx)})"
            )
        except RuntimeError as exc:
            return f"{p.name}: failed - {exc}"

    def _clear_memory(self, ctx: CommandContext, chat_id: int) -> str:
        if ctx.conversation_store is None:
            return "Memory store is not configured."
        project_name = ctx.project_name
        if not project_name:
            return "No project is bound to this bot."
        entries_removed, links_removed = ctx.conversation_store.delete_chat_memory(
            project=project_name, chat_id=chat_id
        )
        return (
            f"Deleted this chat's conversation memory. "
            f"(project={project_name}, entries {entries_removed}, branch links {links_removed})"
        )

    def _clear_worktrees(self, ctx: CommandContext) -> str:
        p = self._bound_project_record(ctx)
        if p is None:
            return "No project is bound to this bot or the project was not found in the registry."
        if not p.enabled:
            return f"Project is disabled: {p.name}"

        try:
            removed_count = ctx.git_service.cleanup_managed_worktrees(
                p.root_path,
                p.worktree_base_dir,
                branch_prefix="remote-",
            )
            return f"{p.name}: {removed_count} worktrees deleted, stale entries pruned"
        except RuntimeError as exc:
            return f"{p.name}: failed - {exc}"


class StopCommand(TelegramCommand):
    name = "/stop"
    description = "Choose and stop a running job"

    def execute(self, message: TelegramMessage, ctx: CommandContext) -> str:
        tokens = message.text.strip().split(maxsplit=1)
        if len(tokens) < 2:
            jobs = self._list_cancellable_jobs(message, ctx)
            if not jobs:
                return "No running job can be stopped."
            return "Choose a job to stop."
        job_id = tokens[1].strip()
        project_name = effective_project_name_for_chat(ctx, message.chat_id)
        existing = ctx.job_store.get(job_id)
        if existing is not None and project_name and existing.request.project != project_name:
            return f"Job not found: {job_id}"
        if ctx.job_manager is None:
            return "Job cancellation is not available."
        success = ctx.job_manager.cancel(job_id)
        if success:
            return f"Stop requested: {job_id}"
        job = ctx.job_store.get(job_id)
        if not job:
            return f"Job not found: {job_id}"
        return f"Cannot stop job: {job_id} (current status: {job.status.value})"

    def get_inline_buttons(
        self,
        message: TelegramMessage | None = None,
        ctx: CommandContext | None = None,
    ) -> list[list[InlineButton]] | None:
        if message is None or ctx is None:
            return None
        if len(message.text.strip().split()) != 1:
            return None
        jobs = self._list_cancellable_jobs(message, ctx)
        if not jobs:
            return None
        return _button_rows(
            [InlineButton(_job_button_label(job), f"/stop {job.id}") for job in jobs],
            per_row=1,
        )

    @staticmethod
    def _list_cancellable_jobs(message: TelegramMessage, ctx: CommandContext) -> list[Job]:
        project_name = effective_project_name_for_chat(ctx, message.chat_id)
        if not project_name:
            return []
        return [
            job
            for job in ctx.job_store.list_recent_for_project_chat(
                project_name, message.chat_id, 20
            )
            if job.status in {JobStatus.QUEUED, JobStatus.RUNNING}
        ]
