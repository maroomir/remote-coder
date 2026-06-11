from __future__ import annotations

from collections.abc import Callable
from functools import partial

from fastapi import BackgroundTasks

from app.jobs.schemas import Job, JobRequest
from app.monitoring.events import EventLogger
from app.security.auth import AllowlistAuthService
from app.telegram.commands import (
    CommandContext,
    CommandRegistry,
    FIX_SOURCE_PENDING_ACTION,
    TelegramMessage,
)
from app.telegram.confirmations import PendingConfirmation
from app.telegram.handlers.presenters import (
    CLOSE_PANEL,
    NATURAL_JOB_CONFIRMATION,
    NATURAL_JOB_CONFIRM_NO,
    NATURAL_JOB_CONFIRM_YES,
    TELEGRAM_TEXT_LIMIT,
    format_natural_job_cancelled,
)
from app.telegram.handlers.request import TelegramCallbackQuery, TelegramUpdate
from app.telegram.notifier import Notifier

_inbound = EventLogger("app.telegram.inbound", "telegram.inbound")
_cmdlog = EventLogger("app.telegram.command", "telegram.command")
_authlog = EventLogger("app.security.auth", "auth.reject")


def telegram_text_preview(text: str, max_len: int = 80) -> str:
    stripped = text.strip()
    if not stripped:
        return ""
    first = stripped.splitlines()[0]
    return first[:max_len]


class CallbackDispatcher:
    def __init__(
        self,
        *,
        command_registry: CommandRegistry,
        submit_confirmed_natural_request: Callable[
            [JobRequest, str, BackgroundTasks], Job
        ],
        submit_confirmed_fix_request: Callable[[JobRequest, str, BackgroundTasks], None],
        handle_plan_execute: Callable[
            [TelegramCallbackQuery, Notifier, str | None, int, int, BackgroundTasks],
            dict[str, str],
        ],
        handle_plan_decision_answer: Callable[
            [TelegramCallbackQuery, Notifier, str | None, int, BackgroundTasks],
            dict[str, str],
        ],
        plan_execute_callback_prefix: str,
        plan_decision_callback_prefix: str,
    ) -> None:
        self._command_registry = command_registry
        self._submit_confirmed_natural_request = submit_confirmed_natural_request
        self._submit_confirmed_fix_request = submit_confirmed_fix_request
        self._handle_plan_execute = handle_plan_execute
        self._handle_plan_decision_answer = handle_plan_decision_answer
        self._plan_execute_callback_prefix = plan_execute_callback_prefix
        self._plan_decision_callback_prefix = plan_decision_callback_prefix

    def handle(
        self,
        update: TelegramUpdate,
        cq: TelegramCallbackQuery,
        notifier: Notifier,
        auth_service: AllowlistAuthService,
        command_context: CommandContext,
        scope_project: str | None,
        background_tasks: BackgroundTasks,
    ) -> dict[str, str]:
        if cq.message is None or not cq.data:
            _inbound.info(
                "callback_query skipped missing message/data update_id=%s has_message=%s has_data=%s",
                update.update_id,
                cq.message is not None,
                bool(cq.data),
            )
            background_tasks.add_task(notifier.answer_callback_query, cq.id)
            return {"status": "ignored"}
        cq_chat_id = cq.message.chat.id
        cq_user_id = cq.from_user.id
        cq_preview = telegram_text_preview(cq.data)
        _inbound.info(
            "callback_query received update_id=%s data=%s",
            update.update_id,
            cq_preview or "(empty)",
            chat_id=cq_chat_id,
            user_id=cq_user_id,
        )
        if not auth_service.is_allowed(chat_id=cq_chat_id, user_id=cq_user_id):
            _authlog.warning(
                "unauthorized callback_query update_id=%s",
                update.update_id,
                chat_id=cq_chat_id,
                user_id=cq_user_id,
            )
            background_tasks.add_task(notifier.answer_callback_query, cq.id)
            return {"status": "ignored"}
        if cq.data == CLOSE_PANEL:
            notifier.answer_callback_query(cq.id, text="Closed.")
            if cq.message.message_id is not None:
                background_tasks.add_task(
                    partial(notifier.edit_message, cq_chat_id, cq.message.message_id, "Closed.", [])
                )
            return {"status": "ok"}
        if cq.data.startswith(f"{self._plan_execute_callback_prefix}:"):
            return self._handle_plan_execute(
                cq, notifier, scope_project, cq_chat_id, cq_user_id, background_tasks
            )
        if cq.data.startswith(f"{self._plan_decision_callback_prefix}:"):
            return self._handle_plan_decision_answer(
                cq, notifier, scope_project, cq_chat_id, background_tasks
            )
        if cq.data in {NATURAL_JOB_CONFIRM_YES, NATURAL_JOB_CONFIRM_NO}:
            return self._handle_confirmation_callback(
                cq, notifier, command_context, scope_project, cq_chat_id, background_tasks
            )
        return self._handle_command_callback(
            cq,
            cq_chat_id,
            cq_user_id,
            cq_preview,
            notifier,
            command_context,
            background_tasks,
        )

    def _handle_confirmation_callback(
        self,
        cq: TelegramCallbackQuery,
        notifier: Notifier,
        command_context: CommandContext,
        scope_project: str | None,
        cq_chat_id: int,
        background_tasks: BackgroundTasks,
    ) -> dict[str, str]:
        notifier.answer_callback_query(cq.id)
        pending = command_context.confirmation_store.get(scope_project, cq_chat_id)
        is_natural = pending is not None and pending.command_name == NATURAL_JOB_CONFIRMATION
        is_fix = (
            pending is not None
            and pending.command_name == "/fix"
            and pending.action == FIX_SOURCE_PENDING_ACTION
        )
        if not (is_natural or is_fix):
            background_tasks.add_task(notifier.send_text, cq_chat_id, "There is no pending confirmation.")
            return {"status": "ignored"}
        confirmed: PendingConfirmation | None = command_context.confirmation_store.pop(
            scope_project, cq_chat_id
        )
        if cq.data == NATURAL_JOB_CONFIRM_NO:
            if is_fix:
                background_tasks.add_task(notifier.send_text, cq_chat_id, "Cancelled the fix job.")
            else:
                background_tasks.add_task(
                    notifier.send_text,
                    cq_chat_id,
                    format_natural_job_cancelled(confirmed.job_request if confirmed else None),
                )
            return {"status": "ok"}
        if is_fix:
            if (
                confirmed is None
                or confirmed.job_request is None
                or confirmed.job_request.parent_job_id is None
            ):
                background_tasks.add_task(
                    notifier.send_text, cq_chat_id, "Could not process the pending confirmation."
                )
                return {"status": "ignored"}
            background_tasks.add_task(
                self._submit_confirmed_fix_request,
                confirmed.job_request,
                confirmed.original_text or confirmed.job_request.instruction,
                background_tasks,
            )
            return {"status": "accepted"}
        if confirmed is None or confirmed.job_request is None or confirmed.original_text is None:
            background_tasks.add_task(notifier.send_text, cq_chat_id, "Could not process the pending confirmation.")
            return {"status": "ignored"}
        job = self._submit_confirmed_natural_request(
            request=confirmed.job_request,
            original_text=confirmed.original_text,
            background_tasks=background_tasks,
        )
        return {"status": "accepted", "job_id": job.id}

    def _handle_command_callback(
        self,
        cq: TelegramCallbackQuery,
        cq_chat_id: int,
        cq_user_id: int,
        cq_preview: str,
        notifier: Notifier,
        command_context: CommandContext,
        background_tasks: BackgroundTasks,
    ) -> dict[str, str]:
        cq_response = self._command_registry.dispatch_rich(
            TelegramMessage(chat_id=cq_chat_id, user_id=cq_user_id, text=cq.data or ""),
            command_context,
        )
        if cq_response is None:
            notifier.answer_callback_query(cq.id)
            _cmdlog.info(
                "callback_query no command response cmd=%s",
                cq_preview or "(empty)",
                chat_id=cq_chat_id,
                user_id=cq_user_id,
            )
            return {"status": "ok"}
        buttons = cq_response.inline_buttons
        mid = cq.message.message_id if cq.message is not None else None
        skip = cq_response.skip_notifier_body_i18n
        too_long = len(cq_response.text) > TELEGRAM_TEXT_LIMIT
        _cmdlog.info(
            "callback_query handled cmd=%s response_len=%d button_rows=%d edit=%s",
            cq_preview or "(empty)",
            len(cq_response.text),
            len(buttons or []),
            cq_response.prefer_edit and mid is not None and not too_long,
            chat_id=cq_chat_id,
            user_id=cq_user_id,
        )
        if cq_response.prefer_edit and mid is not None and not too_long:
            # Navigable panel: edit the originating message in place; fall back to a
            # new message if the edit cannot be applied (message too old / not editable).
            def _edit_or_send(
                chat_id: int = cq_chat_id,
                message_id: int = mid,
                text: str = cq_response.text,
                rows: list | None = buttons,
                skip_body: bool = skip,
            ) -> None:
                if notifier.edit_message(chat_id, message_id, text, rows or [], skip_body_i18n=skip_body):
                    return
                if rows:
                    notifier.send_with_buttons(chat_id, text, rows, skip_body_i18n=skip_body)
                else:
                    notifier.send_text(chat_id, text, skip_body_i18n=skip_body)

            background_tasks.add_task(_edit_or_send)
            notifier.answer_callback_query(cq.id)
        elif buttons and not too_long:
            background_tasks.add_task(
                partial(notifier.send_with_buttons, cq_chat_id, cq_response.text, buttons, skip_body_i18n=skip)
            )
            notifier.answer_callback_query(cq.id)
        else:
            # Terminal result: keep it as a record (new message) with a lightweight toast.
            if too_long:
                background_tasks.add_task(notifier.send_long_text, cq_chat_id, cq_response.text)
            else:
                background_tasks.add_task(
                    partial(notifier.send_text, cq_chat_id, cq_response.text, skip_body_i18n=skip)
                )
            notifier.answer_callback_query(cq.id, text=cq_response.text.split("\n", 1)[0])
        return {"status": "ok"}
