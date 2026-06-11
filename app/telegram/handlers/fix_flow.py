from __future__ import annotations

from app.jobs.manager import JobManager
from app.jobs.schemas import FixKind, Job, JobMode, JobRequest
from app.telegram.commands import (
    FIX_SOURCE_AWAIT_ACTION,
    FIX_SOURCE_PENDING_ACTION,
    effective_project_name_for_chat,
)
from app.telegram.confirmations import PendingConfirmation
from app.telegram.conversation import SQLiteConversationStore
from app.telegram.handlers.presenters import (
    format_fix_mode_input_prompt,
    format_fix_requires_reply_message,
    format_fix_source_confirmation,
    natural_job_confirmation_buttons,
)
from app.telegram.handlers.request import WebhookRequest
from app.telegram.parser import CommandParseError, CommandParser, _extract_reply_job_id


class FixFlow:
    def __init__(
        self,
        *,
        parser: CommandParser,
        job_manager: JobManager,
        conversation_store: SQLiteConversationStore | None,
    ) -> None:
        self._parser = parser
        self._job_manager = job_manager
        self._conversation_store = conversation_store

    def resolve_target_from_reply(self, req: WebhookRequest) -> Job | None:
        project_name = effective_project_name_for_chat(req.command_context, req.chat_id)
        if project_name is None:
            return None
        linked_job_id: str | None = None
        if req.reply_mid is not None and self._conversation_store is not None:
            linked_job_id = self._conversation_store.get_job_id_for_message_id(
                req.scope_project, req.chat_id, req.reply_mid
            )
            if linked_job_id is None and req.reply_txt:
                linked_job_id = _extract_reply_job_id(req.reply_txt)
        if linked_job_id is None:
            return None
        return self._job_manager.resolve_fix_target_job(linked_job_id, project_name, req.chat_id)

    def extract_instruction(self, req: WebhookRequest) -> str | None:
        text = req.message.text.strip()
        tokens = text.split()
        if tokens and tokens[0].lower() == "/fix":
            if len(tokens) == 1:
                return None
            return text.split(maxsplit=1)[1]
        parsed = self._parser.parse_fix_instruction(text)
        return parsed.instruction if parsed is not None else None

    def queue_confirmation(
        self,
        req: WebhookRequest,
        fix_instruction: str,
        target_job: Job,
    ) -> dict[str, str]:
        project_name = effective_project_name_for_chat(req.command_context, req.chat_id)
        if project_name is None:
            req.background_tasks.add_task(req.notifier.send_text, req.chat_id, "No project is registered.")
            return {"status": "ignored"}
        fix_request = JobRequest(
            project=project_name,
            model=target_job.request.model,
            model_id=target_job.request.model_id,
            instruction=fix_instruction,
            mode=JobMode.AGENT_FIX,
            fix_kind=FixKind.SOURCE,
            parent_job_id=target_job.id,
            branch=target_job.branch,
            chat_id=req.chat_id,
            requested_by=req.user_id,
            message_id=req.update.message.message_id if req.update.message is not None else None,
            reply_to_message_id=req.reply_mid,
        )
        req.command_context.confirmation_store.set(
            req.scope_project,
            req.chat_id,
            PendingConfirmation(
                command_name="/fix",
                action=FIX_SOURCE_PENDING_ACTION,
                job_request=fix_request,
                original_text=req.message.text.strip(),
                target_job_id=target_job.id,
            ),
        )
        req.background_tasks.add_task(
            req.notifier.send_with_buttons,
            req.chat_id,
            format_fix_source_confirmation(fix_request, target_job),
            natural_job_confirmation_buttons(),
        )
        return {"status": "ok"}

    def handle_intent(self, req: WebhookRequest) -> dict[str, str] | None:
        try:
            fix_instruction = self.extract_instruction(req)
        except CommandParseError as exc:
            req.background_tasks.add_task(req.notifier.send_text, req.chat_id, str(exc))
            return {"status": "ignored"}
        if fix_instruction is None:
            return None
        if not fix_instruction.strip():
            return None
        target_job = self.resolve_target_from_reply(req)
        if target_job is None:
            req.background_tasks.add_task(
                req.notifier.send_text,
                req.chat_id,
                format_fix_requires_reply_message(),
            )
            return {"status": "ignored"}
        return self.queue_confirmation(req, fix_instruction.strip(), target_job)

    def prompt_for_instruction(self, req: WebhookRequest) -> dict[str, str]:
        target_job = self.resolve_target_from_reply(req)
        if target_job is None:
            req.background_tasks.add_task(
                req.notifier.send_text, req.chat_id, format_fix_requires_reply_message()
            )
            return {"status": "ignored"}
        req.command_context.confirmation_store.set(
            req.scope_project,
            req.chat_id,
            PendingConfirmation(
                command_name="/fix",
                action=FIX_SOURCE_AWAIT_ACTION,
                target_job_id=target_job.id,
                reply_to_message_id=req.reply_mid,
            ),
        )
        req.background_tasks.add_task(req.notifier.send_text, req.chat_id, format_fix_mode_input_prompt())
        return {"status": "ok"}

    def handle_pending(self, req: WebhookRequest, pending: PendingConfirmation) -> dict[str, str] | None:
        if (
            pending.command_name == "/fix"
            and pending.action == FIX_SOURCE_AWAIT_ACTION
            and req.message_head_lower != "/init"
            and not req.message.text.strip().startswith("/")
        ):
            req.command_context.confirmation_store.pop(req.scope_project, req.chat_id)
            project_name = effective_project_name_for_chat(req.command_context, req.chat_id)
            target_job = (
                self._job_manager.resolve_fix_target_job(pending.target_job_id, project_name, req.chat_id)
                if pending.target_job_id is not None and project_name is not None
                else None
            )
            if target_job is None:
                req.background_tasks.add_task(req.notifier.send_text, req.chat_id, "Fix target job is no longer available.")
                return {"status": "ignored"}
            fix_request = JobRequest(
                project=project_name,
                model=target_job.request.model,
                model_id=target_job.request.model_id,
                instruction=req.message.text.strip(),
                mode=JobMode.AGENT_FIX,
                fix_kind=FixKind.SOURCE,
                parent_job_id=target_job.id,
                branch=target_job.branch,
                chat_id=req.chat_id,
                requested_by=req.user_id,
                message_id=req.update.message.message_id if req.update.message is not None else None,
                reply_to_message_id=pending.reply_to_message_id or req.reply_mid,
            )
            req.command_context.confirmation_store.set(
                req.scope_project,
                req.chat_id,
                PendingConfirmation(
                    command_name="/fix",
                    action=FIX_SOURCE_PENDING_ACTION,
                    job_request=fix_request,
                    original_text=req.message.text.strip(),
                    target_job_id=target_job.id,
                ),
            )
            req.background_tasks.add_task(
                req.notifier.send_with_buttons,
                req.chat_id,
                format_fix_source_confirmation(fix_request, target_job),
                natural_job_confirmation_buttons(),
            )
            return {"status": "ok"}

        if (
            pending.command_name == "/fix"
            and pending.action == FIX_SOURCE_PENDING_ACTION
            and req.message_head_lower != "/init"
        ):
            # Confirmation is button-only (Yes/No); any typed message cancels the pending fix.
            req.command_context.confirmation_store.pop(req.scope_project, req.chat_id)
            req.background_tasks.add_task(req.notifier.send_text, req.chat_id, "Cancelled the fix job.")
            return {"status": "ignored"}

        return None
