from __future__ import annotations

from app.jobs.mode_registry import get_mode_registry
from app.jobs.schemas import JobMode, JobRequest
from app.monitoring.events import EventLogger
from app.telegram.confirmations import PendingConfirmation
from app.telegram.handlers.presenters import (
    NATURAL_JOB_CONFIRMATION,
    NATURAL_JOB_MODE_INPUT,
    format_mode_input_prompt,
    format_natural_job_cancelled,
    format_natural_job_confirmation,
    natural_job_confirmation_buttons,
)
from app.telegram.handlers.request import WebhookRequest
from app.telegram.parser import CommandParseError, CommandParser

_cmdlog = EventLogger("app.telegram.command", "telegram.command")


class NaturalFlow:
    def __init__(self, *, parser: CommandParser) -> None:
        self._parser = parser

    def queue_confirmation(
        self,
        req: WebhookRequest,
        request: JobRequest,
        original_text_stripped: str,
    ) -> bool:
        cc = req.command_context
        ent = cc.project_registry.get(req.scope_project)
        if ent is None:
            req.background_tasks.add_task(
                req.notifier.send_text,
                req.chat_id,
                f"Unknown project: {req.scope_project}",
            )
            return False
        try:
            current_branch = str(cc.git_service.get_current_branch(ent.root_path))
        except RuntimeError as exc:
            req.background_tasks.add_task(
                req.notifier.send_text, req.chat_id, f"Could not resolve work branch: {exc}"
            )
            return False
        cc.confirmation_store.set(
            req.scope_project,
            req.chat_id,
            PendingConfirmation(
                command_name=NATURAL_JOB_CONFIRMATION,
                action="submit",
                job_request=request,
                original_text=original_text_stripped,
            ),
        )
        req.background_tasks.add_task(
            req.notifier.send_with_buttons,
            req.chat_id,
            format_natural_job_confirmation(request, current_branch),
            natural_job_confirmation_buttons(),
        )
        return True

    def handle_pending(
        self,
        req: WebhookRequest,
        pending: PendingConfirmation,
    ) -> dict[str, str] | None:
        if pending.command_name == NATURAL_JOB_CONFIRMATION and req.message_head_lower != "/init":
            return self._replace_pending_confirmation(req, pending)

        if pending.command_name == NATURAL_JOB_MODE_INPUT and req.message_head_lower != "/init":
            return self._parse_pending_mode_input(req, pending)

        return None

    def prompt_for_mode_instruction(
        self, req: WebhookRequest, mode: JobMode | str
    ) -> dict[str, str]:
        mode_name = mode.value if isinstance(mode, JobMode) else str(mode)
        req.command_context.confirmation_store.set(
            req.scope_project,
            req.chat_id,
            PendingConfirmation(
                command_name=NATURAL_JOB_MODE_INPUT,
                action=mode_name,
            ),
        )
        req.background_tasks.add_task(
            req.notifier.send_text, req.chat_id, format_mode_input_prompt(mode)
        )
        return {"status": "ok"}

    def handle_natural(self, req: WebhookRequest) -> dict[str, str]:
        try:
            request = self._parser.parse_natural(
                req.message.text,
                req.scope_project,
                chat_id=req.chat_id,
                user_id=req.user_id,
                message_id=req.update.message.message_id if req.update.message is not None else None,
                reply_to_message_id=req.reply_mid,
                reply_to_text=req.reply_txt,
            )
        except CommandParseError as exc:
            _cmdlog.warning(
                "parse error message_id=%s err=%s",
                req.update.message.message_id if req.update.message is not None else None,
                str(exc)[:120],
                chat_id=req.chat_id,
                user_id=req.user_id,
            )
            req.background_tasks.add_task(req.notifier.send_text, req.chat_id, str(exc))
            return {"status": "ignored"}

        _cmdlog.info(
            "natural request parsed mode=%s model=%s branch=%s commit=%s instruction_len=%d reply_to=%s",
            request.mode.value,
            request.model.value,
            request.branch or "-",
            request.commit,
            len(request.instruction),
            request.reply_to_message_id or "-",
            chat_id=req.chat_id,
            user_id=req.user_id,
            project=request.project,
        )

        if self.queue_confirmation(req, request, req.message.text.strip()):
            return {"status": "ok"}
        return {"status": "ignored"}

    def _replace_pending_confirmation(
        self,
        req: WebhookRequest,
        pending: PendingConfirmation,
    ) -> dict[str, str]:
        cc = req.command_context
        try:
            parsed_request = self._parser.parse_natural(
                req.message.text,
                req.scope_project,
                chat_id=req.chat_id,
                user_id=req.user_id,
                message_id=req.update.message.message_id if req.update.message is not None else None,
                reply_to_message_id=req.reply_mid,
                reply_to_text=req.reply_txt,
            )
        except CommandParseError as exc:
            cc.confirmation_store.pop(req.scope_project, req.chat_id)
            _cmdlog.warning(
                "parse error replacing pending message_id=%s err=%s",
                req.update.message.message_id if req.update.message is not None else None,
                str(exc)[:120],
                chat_id=req.chat_id,
                user_id=req.user_id,
            )
            req.background_tasks.add_task(req.notifier.send_text, req.chat_id, format_natural_job_cancelled(pending.job_request))
            req.background_tasks.add_task(req.notifier.send_text, req.chat_id, str(exc))
            return {"status": "ignored"}
        cc.confirmation_store.pop(req.scope_project, req.chat_id)
        _cmdlog.info(
            "natural pending replaced mode=%s model=%s branch=%s commit=%s instruction_len=%d reply_to=%s",
            parsed_request.mode.value,
            parsed_request.model.value,
            parsed_request.branch or "-",
            parsed_request.commit,
            len(parsed_request.instruction),
            parsed_request.reply_to_message_id or "-",
            chat_id=req.chat_id,
            user_id=req.user_id,
            project=parsed_request.project,
        )
        if self.queue_confirmation(req, parsed_request, req.message.text.strip()):
            return {"status": "ok"}
        return {"status": "ignored"}

    def _parse_pending_mode_input(
        self,
        req: WebhookRequest,
        pending: PendingConfirmation,
    ) -> dict[str, str]:
        cc = req.command_context
        cc.confirmation_store.pop(req.scope_project, req.chat_id)
        spec = get_mode_registry().lookup(pending.action)
        mode_prefix = f"/{pending.action}" if spec is not None and spec.slash else "/ask"
        try:
            parsed_request = self._parser.parse_natural(
                f"{mode_prefix} {req.message.text}",
                req.scope_project,
                chat_id=req.chat_id,
                user_id=req.user_id,
                message_id=req.update.message.message_id if req.update.message is not None else None,
                reply_to_message_id=req.reply_mid,
                reply_to_text=req.reply_txt,
            )
        except CommandParseError as exc:
            _cmdlog.warning(
                "parse error for pending mode input message_id=%s mode=%s err=%s",
                req.update.message.message_id if req.update.message is not None else None,
                pending.action,
                str(exc)[:120],
                chat_id=req.chat_id,
                user_id=req.user_id,
            )
            req.background_tasks.add_task(req.notifier.send_text, req.chat_id, str(exc))
            return {"status": "ignored"}
        _cmdlog.info(
            "pending mode input parsed mode=%s model=%s instruction_len=%d reply_to=%s",
            parsed_request.mode.value,
            parsed_request.model.value,
            len(parsed_request.instruction),
            parsed_request.reply_to_message_id or "-",
            chat_id=req.chat_id,
            user_id=req.user_id,
            project=parsed_request.project,
        )
        if self.queue_confirmation(req, parsed_request, req.message.text.strip()):
            return {"status": "ok"}
        return {"status": "ignored"}
