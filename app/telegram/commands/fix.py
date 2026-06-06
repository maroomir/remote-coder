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
    menu_text = "수정 대상을 선택하세요."
    description = "이전 Job의 커밋 또는 소스를 다시 수정합니다"

    _MAX_CANDIDATES = 8

    def execute(self, message: TelegramMessage, ctx: CommandContext) -> str:
        tokens = message.text.strip().split()
        if ctx.job_manager is None:
            return "수정 기능을 사용할 수 없습니다."
        if len(tokens) == 1:
            return "수정할 항목을 선택하세요."
        if len(tokens) == 2:
            kind = tokens[1].lower()
            if kind not in {"commit", "source"}:
                return format_usage("/fix", "/fix commit", "/fix source")
            candidates = self._list_candidates(message, ctx)
            if not candidates:
                return "수정 가능한 Job이 없습니다."
            return "수정 대상 Job을 선택하세요."
        if len(tokens) >= 3:
            kind = tokens[1].lower()
            if kind not in {"commit", "source"}:
                return format_usage("/fix", "/fix commit", "/fix source")
            job_id = tokens[2].strip()
            project_name = effective_project_name_for_chat(ctx, message.chat_id)
            if not project_name:
                return "등록된 프로젝트가 없습니다."
            target_job = ctx.job_store.get(job_id)
            if target_job is None or not ctx.job_manager.is_fix_candidate(
                target_job, project_name, message.chat_id
            ):
                return f"수정 대상으로 사용할 수 없는 Job입니다: {job_id}"
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
            f"커밋 메시지 재생성 미리보기 (Job {target_job.id}, 브랜치 {target_job.branch})",
            "",
            prepared_message,
            "",
            "적용하려면 y/Y, 취소하려면 n/N (또는 버튼).",
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
            f"Job {target_job.id} 에 대한 수정 지시를 보내주세요. "
            "다음 메시지를 그대로 지시로 사용합니다."
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
        return "확인 대기 작업을 처리할 수 없습니다."

    def _confirm_commit(
        self,
        message: TelegramMessage,
        ctx: CommandContext,
        pending: PendingConfirmation,
    ) -> str:
        if message.text.strip() not in {"y", "Y"}:
            return "커밋 메시지 수정을 취소했습니다."
        if ctx.job_manager is None or not pending.target_job_id or not pending.prepared_payload:
            return "확인 대기 작업을 처리할 수 없습니다."
        target_job = ctx.job_store.get(pending.target_job_id)
        project_name = effective_project_name_for_chat(ctx, message.chat_id)
        if target_job is None or not project_name or not ctx.job_manager.is_fix_candidate(
            target_job, project_name, message.chat_id
        ):
            return "수정 대상 Job을 더 이상 사용할 수 없습니다."
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
                f"커밋 메시지를 수정했습니다.\n"
                f"- Job: {result_job.id}\n"
                f"- 브랜치: {result_job.branch}\n"
                f"- 새 커밋: {result_job.commit_hash}"
            )
        return f"커밋 메시지 수정 실패: {result_job.error or 'unknown'}"

    def _confirm_source(
        self,
        message: TelegramMessage,
        ctx: CommandContext,
        pending: PendingConfirmation,
    ) -> str:
        # Source-mode confirmation is routed by the webhook (background task);
        # see app/telegram/webhook.py for the actual execution.
        _ = (message, ctx, pending)
        return "수정 작업을 백그라운드로 시작했습니다."

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
                    InlineButton("커밋 수정 (commit)", "/fix commit"),
                    InlineButton("소스 수정 (source)", "/fix source"),
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
