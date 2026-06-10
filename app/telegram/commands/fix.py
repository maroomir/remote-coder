from __future__ import annotations

from app.jobs.schemas import Job
from app.telegram.commands.base import (
    CommandContext,
    ConfirmableCommand,
    InlineButton,
    TelegramMessage,
    _button_rows,
    effective_project_name_for_chat,
    format_usage,
)
from app.telegram.confirmations import PendingConfirmation

FIX_SOURCE_AWAIT_ACTION = "fix_source_await_instruction"
FIX_SOURCE_PENDING_ACTION = "fix_source"


def _fix_job_button_label(job: Job) -> str:
    short_hash = (job.commit_hash or "")[:8]
    branch = job.branch or "-"
    return f"{job.id} ({branch}) [{short_hash}]"


class FixCommand(ConfirmableCommand):
    name = "/fix"
    menu_text = "Choose a job to fix."
    description = "Fix the source of a previous job (amend + force-with-lease push)"

    _MAX_CANDIDATES = 8

    def execute(self, message: TelegramMessage, ctx: CommandContext) -> str:
        tokens = message.text.strip().split()
        if ctx.job_manager is None:
            return "Fix feature is not available."
        if len(tokens) == 1:
            candidates = self._list_candidates(message, ctx)
            if not candidates:
                return "No job is available to fix."
            return "Choose a job to fix."
        if len(tokens) == 2:
            job_id = tokens[1].strip()
            project_name = effective_project_name_for_chat(ctx, message.chat_id)
            if not project_name:
                return "No project is registered."
            target_job = ctx.job_store.get(job_id)
            if target_job is None or not ctx.job_manager.is_fix_candidate(
                target_job, project_name, message.chat_id
            ):
                return f"Job cannot be used as a fix target: {job_id}"
            return self._start_source_fix(message, ctx, target_job)
        return format_usage("/fix", "/fix <job_id>")

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
        if pending.action == FIX_SOURCE_PENDING_ACTION:
            return self._confirm_source(message, ctx, pending)
        return "Could not process the pending confirmation."

    def _confirm_source(
        self,
        message: TelegramMessage,
        ctx: CommandContext,
        pending: PendingConfirmation,
    ) -> str:
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
            candidates = self._list_candidates(message, ctx)
            if not candidates:
                return None
            return _button_rows(
                [
                    InlineButton(_fix_job_button_label(job), f"/fix {job.id}")
                    for job in candidates
                ],
                per_row=1,
            )
        return None

    def _list_candidates(self, message: TelegramMessage, ctx: CommandContext) -> list[Job]:
        if ctx.job_manager is None:
            return []
        project_name = effective_project_name_for_chat(ctx, message.chat_id)
        if not project_name:
            return []
        return ctx.job_manager.list_fix_candidates(
            project_name, message.chat_id, limit=self._MAX_CANDIDATES
        )
