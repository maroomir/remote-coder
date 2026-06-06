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
    _confirmation_buttons_enabled,
    _job_button_label,
    effective_project_name_for_chat,
)
from app.telegram.confirmations import PendingConfirmation


class ClearCommand(ConfirmableCommand):
    name = "/clear"
    description = "브랜치, worktree, 대화 기억을 확인 후 정리합니다"

    def execute(self, message: TelegramMessage, ctx: CommandContext) -> str:
        tokens = message.text.strip().split()
        if len(tokens) == 1:
            return "Choose what to clear. Confirmation with y/Y is required before running."
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
        if _confirmation_buttons_enabled(ctx):
            return f"Pending action: {summary}\nChoose whether to run it."
        return (
            f"Pending action: {summary}\n"
            "Send y or Y to run it. Any other response cancels it."
        )

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
        if not _confirmation_buttons_enabled(ctx):
            return None
        pending = ctx.confirmation_store.get(
            effective_project_name_for_chat(ctx, message.chat_id),
            message.chat_id,
        )
        if pending is None or pending.command_name != self.name:
            return None
        return [[InlineButton("Yes", "Y"), InlineButton("No", "n")]]

    def confirm(
        self,
        message: TelegramMessage,
        ctx: CommandContext,
        pending: PendingConfirmation,
    ) -> str:
        if message.text.strip() not in {"y", "Y"}:
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
                p.root_path, ctx.git_remote_name, "remote-"
            )
            local_branches = ctx.git_service.list_local_branches_matching(p.root_path, "remote-")
            if remote_branches:
                ctx.git_service.delete_remote_branches(p.root_path, ctx.git_remote_name, remote_branches)
            if local_branches:
                ctx.git_service.remove_linked_worktrees_for_branches(p.root_path, local_branches)
                ctx.git_service.delete_local_branches(p.root_path, local_branches)
            return (
                f"{p.name}: remote {len(remote_branches)}, local {len(local_branches)} deleted "
                f"({ctx.git_remote_name})"
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
    description = "진행 중인 Job을 선택해 중단합니다"

    def execute(self, message: TelegramMessage, ctx: CommandContext) -> str:
        tokens = message.text.strip().split(maxsplit=1)
        if len(tokens) < 2:
            jobs = self._list_cancellable_jobs(message, ctx)
            if not jobs:
                return "중단할 수 있는 진행 중 Job이 없습니다."
            return "중단할 Job을 선택하세요."
        job_id = tokens[1].strip()
        project_name = effective_project_name_for_chat(ctx, message.chat_id)
        existing = ctx.job_store.get(job_id)
        if existing is not None and project_name and existing.request.project != project_name:
            return f"Job을 찾을 수 없습니다: {job_id}"
        if ctx.job_manager is None:
            return "작업 중단 기능을 사용할 수 없습니다."
        success = ctx.job_manager.cancel(job_id)
        if success:
            return f"작업 중단 요청 완료: {job_id}"
        job = ctx.job_store.get(job_id)
        if not job:
            return f"Job을 찾을 수 없습니다: {job_id}"
        return f"작업을 중단할 수 없습니다: {job_id} (현재 상태: {job.status.value})"

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
