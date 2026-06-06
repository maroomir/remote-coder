from __future__ import annotations

from app.jobs.schemas import FixKind, Job, JobMode, JobRequest
from app.telegram.commands.base import (
    CommandContext,
    ConfirmableCommand,
    InlineButton,
    TelegramMessage,
    _button_rows,
    _confirmation_buttons_enabled,
    effective_project_name_for_chat,
    format_usage,
)
from app.telegram.confirmations import PendingConfirmation

FIX_SOURCE_AWAIT_ACTION = "fix_source_await_instruction"
FIX_COMMIT_PENDING_ACTION = "fix_commit"
FIX_SOURCE_PENDING_ACTION = "fix_source"


def _fix_job_button_label(job: Job) -> str:
    short_hash = (job.commit_hash or "")[:8]
    branch = job.branch or "-"
    return f"{job.id} ({branch}) [{short_hash}]"


class FixCommand(ConfirmableCommand):
    name = "/fix"
    menu_text = "Choose what to fix."
    description = "Re-do the commit or source of a previous job"

    _MAX_CANDIDATES = 8

    def execute(self, message: TelegramMessage, ctx: CommandContext) -> str:
        tokens = message.text.strip().split()
        if ctx.job_manager is None:
            return "Fix feature is not available."
        if len(tokens) == 1:
            return "Choose what to fix."
        if len(tokens) == 2:
            kind = tokens[1].lower()
            if kind not in {"commit", "source"}:
                return format_usage("/fix", "/fix commit", "/fix source")
            candidates = self._list_candidates(message, ctx)
            if not candidates:
                return "No job is available to fix."
            return "Choose a job to fix."
        if len(tokens) >= 3:
            kind = tokens[1].lower()
            if kind not in {"commit", "source"}:
                return format_usage("/fix", "/fix commit", "/fix source")
            job_id = tokens[2].strip()
            project_name = effective_project_name_for_chat(ctx, message.chat_id)
            if not project_name:
                return "No project is registered."
            target_job = ctx.job_store.get(job_id)
            if target_job is None or not ctx.job_manager.is_fix_candidate(
                target_job, project_name, message.chat_id
            ):
                return f"Job cannot be used as a fix target: {job_id}"
            if kind == "commit":
                return self._start_commit_fix(message, ctx, target_job)
            return self._start_source_fix(message, ctx, target_job)
        return format_usage("/fix", "/fix commit", "/fix source")

    def _start_commit_fix(
        self, message: TelegramMessage, ctx: CommandContext, target_job: Job
    ) -> str:
        assert ctx.job_manager is not None
        prepared_message = ctx.job_manager.build_fix_commit_preview(target_job)
        ctx.confirmation_store.set(
            effective_project_name_for_chat(ctx, message.chat_id),
            message.chat_id,
            PendingConfirmation(
                command_name=self.name,
                action=FIX_COMMIT_PENDING_ACTION,
                target_job_id=target_job.id,
                prepared_payload=prepared_message,
            ),
        )
        lines = [
            f"Commit message preview (Job {target_job.id}, branch {target_job.branch})",
            "",
            prepared_message,
            "",
            "Send y/Y to apply, or n/N to cancel (or use buttons).",
        ]
        return "\n".join(lines)

    def _start_source_fix(
        self, message: TelegramMessage, ctx: CommandContext, target_job: Job
    ) -> str:
        ctx.confirmation_store.set(
            effective_project_name_for_chat(ctx, message.chat_id),
            message.chat_id,
            PendingConfirmation(
                command_name=self.name,
                action=FIX_SOURCE_AWAIT_ACTION,
                target_job_id=target_job.id,
            ),
        )
        return (
            f"Send the fix instruction for Job {target_job.id}. "
            "The next message will be used as the instruction."
        )

    def confirm(
        self,
        message: TelegramMessage,
        ctx: CommandContext,
        pending: PendingConfirmation,
    ) -> str:
        if pending.action == FIX_COMMIT_PENDING_ACTION:
            return self._confirm_commit(message, ctx, pending)
        if pending.action == FIX_SOURCE_PENDING_ACTION:
            return self._confirm_source(message, ctx, pending)
        return "Could not process the pending confirmation."

    def _confirm_commit(
        self,
        message: TelegramMessage,
        ctx: CommandContext,
        pending: PendingConfirmation,
    ) -> str:
        if message.text.strip() not in {"y", "Y"}:
            return "Cancelled the commit message fix."
        if ctx.job_manager is None or not pending.target_job_id or not pending.prepared_payload:
            return "Could not process the pending confirmation."
        target_job = ctx.job_store.get(pending.target_job_id)
        project_name = effective_project_name_for_chat(ctx, message.chat_id)
        if target_job is None or not project_name or not ctx.job_manager.is_fix_candidate(
            target_job, project_name, message.chat_id
        ):
            return "Fix target job is no longer available."
        request = JobRequest(
            project=project_name,
            model=target_job.request.model,
            model_id=target_job.request.model_id,
            instruction=target_job.request.instruction,
            mode=JobMode.AGENT_FIX,
            fix_kind=FixKind.COMMIT,
            parent_job_id=target_job.id,
            branch=target_job.branch,
            chat_id=message.chat_id,
            requested_by=message.user_id,
        )
        result_job = ctx.job_manager.execute_fix_job(
            request, prepared_message=pending.prepared_payload
        )
        if result_job.status.value == "succeeded":
            return (
                f"Commit message updated.\n"
                f"- Job: {result_job.id}\n"
                f"- Branch: {result_job.branch}\n"
                f"- New commit: {result_job.commit_hash}"
            )
        return f"Commit message fix failed: {result_job.error or 'unknown'}"

    def _confirm_source(
        self,
        message: TelegramMessage,
        ctx: CommandContext,
        pending: PendingConfirmation,
    ) -> str:
        # Source-mode confirmation is routed by the webhook (background task);
        # see app/telegram/webhook.py for the actual execution.
        _ = (message, ctx, pending)
        return "Started the fix job in the background."

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
                    InlineButton("Fix commit", "/fix commit"),
                    InlineButton("Fix source", "/fix source"),
                ],
            ]
        if len(tokens) == 2:
            kind = tokens[1].lower()
            if kind not in {"commit", "source"}:
                return None
            candidates = self._list_candidates(message, ctx)
            if not candidates:
                return None
            return _button_rows(
                [
                    InlineButton(_fix_job_button_label(job), f"/fix {kind} {job.id}")
                    for job in candidates
                ],
                per_row=1,
            )
        if not _confirmation_buttons_enabled(ctx):
            return None
        pending = ctx.confirmation_store.get(
            effective_project_name_for_chat(ctx, message.chat_id),
            message.chat_id,
        )
        if pending is None or pending.command_name != self.name:
            return None
        if pending.action != FIX_COMMIT_PENDING_ACTION:
            return None
        return [[InlineButton("Yes", "Y"), InlineButton("No", "n")]]

    def _list_candidates(self, message: TelegramMessage, ctx: CommandContext) -> list[Job]:
        if ctx.job_manager is None:
            return []
        project_name = effective_project_name_for_chat(ctx, message.chat_id)
        if not project_name:
            return []
        return ctx.job_manager.list_fix_candidates(
            project_name, message.chat_id, limit=self._MAX_CANDIDATES
        )
