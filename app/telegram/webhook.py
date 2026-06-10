from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass, replace
from functools import partial
from threading import Lock

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException
from pydantic import BaseModel, Field

from app.ai.model_catalog import format_model_selection
from app.ai.usage import format_token_usage
from app.jobs.manager import JobManager
from app.jobs.schemas import FixKind, Job, JobMode, JobRequest
from app.jobs.store import JobStore
from app.monitoring.events import EventLogger
from app.security.auth import AllowlistAuthService
from app.telegram.commands import (
    CommandContext,
    CommandRegistry,
    CommandResponse,
    FIX_SOURCE_AWAIT_ACTION,
    FIX_SOURCE_PENDING_ACTION,
    NAV_CLOSE_CALLBACK,
    InlineButton,
    TelegramMessage,
    effective_project_name_for_chat,
)
from app.projects.registry import normalize_webhook_token_hash_path_segment
from app.telegram.bot_instances import BotInstanceManager
from app.telegram.confirmations import PendingConfirmation
from app.telegram.conversation import SQLiteConversationStore
from app.telegram.notifier import Notifier
from app.telegram.parser import CommandParseError, CommandParser, _extract_reply_job_id

_inbound = EventLogger("app.telegram.inbound", "telegram.inbound")
_cmdlog = EventLogger("app.telegram.command", "telegram.command")
_authlog = EventLogger("app.security.auth", "auth.reject")


def _telegram_text_preview(text: str, max_len: int = 80) -> str:
    stripped = text.strip()
    if not stripped:
        return ""
    first = stripped.splitlines()[0]
    return first[:max_len]


_JOB_RESULT_MEMORY_READ_ONLY_STDOUT_PREVIEW = 800


def format_job_result_memory_summary(final_job: Job) -> str:
    summary = f"status={final_job.status.value}"
    if final_job.error_stage:
        summary += f" stage={final_job.error_stage}"
    if final_job.error:
        summary += f" err={str(final_job.error)[:300]}"
    requested_model = format_model_selection(final_job.request.model, final_job.request.model_id)
    summary += f" model={final_job.runner_actual_model or requested_model}"
    token_usage = format_token_usage(final_job.runner_token_usage)
    if token_usage:
        summary += f" tokens={token_usage}"
    if final_job.request.mode in (JobMode.PLAN, JobMode.ASK) and final_job.runner_stdout_summary:
        preview = final_job.runner_stdout_summary[:_JOB_RESULT_MEMORY_READ_ONLY_STDOUT_PREVIEW]
        summary += f" stdout_preview={preview}"
    return summary


_NATURAL_JOB_CONFIRMATION = "__natural_job__"
_NATURAL_JOB_CONFIRM_YES = "__natural_job__:yes"
_NATURAL_JOB_CONFIRM_NO = "__natural_job__:no"
_NATURAL_JOB_MODE_INPUT = "__natural_job_mode_input__"
_CLOSE_PANEL = NAV_CLOSE_CALLBACK
_TELEGRAM_TEXT_LIMIT = 4096


class _RecentUpdateTracker:
    def __init__(self, max_size: int = 1024) -> None:
        self._max_size = max_size
        self._seen: set[tuple[str, int]] = set()
        self._order: deque[tuple[str, int]] = deque()
        self._lock = Lock()

    def mark_seen(self, route_key: str, update_id: int) -> bool:
        key = (route_key, update_id)
        with self._lock:
            if key in self._seen:
                return True
            self._seen.add(key)
            self._order.append(key)
            while len(self._order) > self._max_size:
                old = self._order.popleft()
                self._seen.discard(old)
            return False


def _format_natural_job_confirmation(
    request: JobRequest,
    current_branch: str,
) -> str:
    lines = [
        "Confirm the work to run.",
        "",
        f"- Project: {request.project}",
        f"- Work branch: {current_branch}",
        f"- Model: {format_model_selection(request.model, request.model_id)}",
    ]
    if request.mode is JobMode.PLAN:
        lines.append("- Mode: plan (read-only, no commit/push)")
    elif request.mode is JobMode.ASK:
        lines.append("- Mode: ask (read-only, no commit/push)")
    else:
        lines.append("- Mode: agent (may edit code, commit, and push)")
    if request.branch:
        lines.append(f"- Requested branch: {request.branch}")
    lines.extend(["", "Choose whether to run it."])
    return "\n".join(lines)


def _format_fix_source_confirmation(
    request: JobRequest,
    target_job: Job,
) -> str:
    lines = [
        "Confirm the fix job.",
        "",
        f"- Project: {request.project}",
        f"- Target Job: {target_job.id}",
        f"- Branch: {target_job.branch}",
        f"- Original commit: {target_job.commit_hash}",
        f"- Model: {format_model_selection(request.model, request.model_id)}",
        "- Mode: fix (amends the existing commit and pushes with --force-with-lease)",
        "",
        "Choose whether to run it.",
    ]
    return "\n".join(lines)


def _natural_job_confirmation_buttons() -> list[list[InlineButton]]:
    return [[InlineButton("Yes", _NATURAL_JOB_CONFIRM_YES), InlineButton("No", _NATURAL_JOB_CONFIRM_NO)]]


def _format_natural_job_cancelled(request: JobRequest | None) -> str:
    if request is None:
        return "Cancelled the work request."
    return (
        "Cancelled the work request. "
        f"(project: {request.project}, model: {format_model_selection(request.model, request.model_id)})"
    )


def _format_mode_input_prompt(mode: JobMode) -> str:
    if mode is JobMode.PLAN:
        return (
            "Send the instruction to run in plan mode.\n\n"
            "Example: Plan a login fix\n"
            "Example: model: codex List only API boundary risks"
        )
    if mode is JobMode.ASK:
        return (
            "Send the question to run in ask mode.\n\n"
            "Example: Explain the JobManager flow\n"
            "Example: model: codex How do I run pytest?"
        )
    raise AssertionError(mode)


def _format_fix_mode_input_prompt() -> str:
    return (
        "Send the fix instruction to run in fix mode.\n\n"
        "Example: add missing tests\n"
        "Example: fix: patch the login validation bug"
    )


def _format_fix_requires_reply_message() -> str:
    return (
        "Fix mode requires replying to a job result message.\n\n"
        "Example: reply to a job result, then send /fix\n"
        "Example: reply to a job result with fix: add missing tests"
    )


class TelegramChat(BaseModel):
    id: int


class TelegramUser(BaseModel):
    id: int


class TelegramReplyMessage(BaseModel):
    message_id: int
    text: str | None = None


class TelegramIncomingMessage(BaseModel):
    message_id: int | None = None
    text: str | None = None
    chat: TelegramChat
    from_user: TelegramUser | None = Field(default=None, alias="from")
    reply_to_message: TelegramReplyMessage | None = None

    model_config = {"populate_by_name": True}


class TelegramCallbackQueryFrom(BaseModel):
    id: int


class TelegramCallbackQueryMessage(BaseModel):
    chat: TelegramChat
    message_id: int | None = None


class TelegramCallbackQuery(BaseModel):
    id: str
    from_user: TelegramCallbackQueryFrom = Field(alias="from")
    message: TelegramCallbackQueryMessage | None = None
    data: str | None = None

    model_config = {"populate_by_name": True}


class TelegramUpdate(BaseModel):
    update_id: int
    message: TelegramIncomingMessage | None = None
    callback_query: TelegramCallbackQuery | None = None


@dataclass
class _Req:
    update: TelegramUpdate
    background_tasks: BackgroundTasks
    notifier: Notifier
    command_context: CommandContext
    scope_project: str | None
    chat_id: int
    user_id: int | None
    message: TelegramMessage
    message_head_lower: str
    reply_mid: int | None
    reply_txt: str | None


def create_webhook_router(
    bot_instance_manager: BotInstanceManager,
    parser: CommandParser,
    command_registry: CommandRegistry,
    job_manager: JobManager,
    job_store: JobStore,
    conversation_store: SQLiteConversationStore | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/telegram", tags=["telegram"])
    recent_updates = _RecentUpdateTracker()

    def _handle_callback_query(
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
        cq_preview = _telegram_text_preview(cq.data)
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
        if cq.data == _CLOSE_PANEL:
            notifier.answer_callback_query(cq.id, text="Closed.")
            if cq.message.message_id is not None:
                background_tasks.add_task(
                    partial(notifier.edit_message, cq_chat_id, cq.message.message_id, "Closed.", [])
                )
            return {"status": "ok"}
        if cq.data in {_NATURAL_JOB_CONFIRM_YES, _NATURAL_JOB_CONFIRM_NO}:
            notifier.answer_callback_query(cq.id)
            pending = command_context.confirmation_store.get(scope_project, cq_chat_id)
            is_natural = pending is not None and pending.command_name == _NATURAL_JOB_CONFIRMATION
            is_fix = (
                pending is not None
                and pending.command_name == "/fix"
                and pending.action == FIX_SOURCE_PENDING_ACTION
            )
            if not (is_natural or is_fix):
                background_tasks.add_task(notifier.send_text, cq_chat_id, "There is no pending confirmation.")
                return {"status": "ignored"}
            confirmed = command_context.confirmation_store.pop(scope_project, cq_chat_id)
            if cq.data == _NATURAL_JOB_CONFIRM_NO:
                if is_fix:
                    background_tasks.add_task(notifier.send_text, cq_chat_id, "Cancelled the fix job.")
                else:
                    background_tasks.add_task(
                        notifier.send_text,
                        cq_chat_id,
                        _format_natural_job_cancelled(confirmed.job_request if confirmed else None),
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
                    _submit_confirmed_fix_request,
                    confirmed.job_request,
                    confirmed.original_text or confirmed.job_request.instruction,
                    background_tasks,
                )
                return {"status": "accepted"}
            if confirmed is None or confirmed.job_request is None or confirmed.original_text is None:
                background_tasks.add_task(notifier.send_text, cq_chat_id, "Could not process the pending confirmation.")
                return {"status": "ignored"}
            job = _submit_confirmed_natural_request(
                request=confirmed.job_request,
                original_text=confirmed.original_text,
                background_tasks=background_tasks,
            )
            return {"status": "accepted", "job_id": job.id}
        cq_message = TelegramMessage(chat_id=cq_chat_id, user_id=cq_user_id, text=cq.data)
        cq_response = command_registry.dispatch_rich(cq_message, command_context)
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
        mid = cq.message.message_id
        skip = cq_response.skip_notifier_body_i18n
        too_long = len(cq_response.text) > _TELEGRAM_TEXT_LIMIT
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

    def _queue_natural_confirmation(req: _Req, request: JobRequest, original_text_stripped: str) -> bool:
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
                command_name=_NATURAL_JOB_CONFIRMATION,
                action="submit",
                job_request=request,
                original_text=original_text_stripped,
            ),
        )
        confirmation_text = _format_natural_job_confirmation(request, current_branch)
        req.background_tasks.add_task(
            req.notifier.send_with_buttons,
            req.chat_id,
            confirmation_text,
            _natural_job_confirmation_buttons(),
        )
        return True

    def _resolve_fix_target_from_reply(req: _Req) -> Job | None:
        project_name = effective_project_name_for_chat(req.command_context, req.chat_id)
        if project_name is None:
            return None
        linked_job_id: str | None = None
        if req.reply_mid is not None and conversation_store is not None:
            linked_job_id = conversation_store.get_job_id_for_message_id(
                req.scope_project, req.chat_id, req.reply_mid
            )
            if linked_job_id is None and req.reply_txt:
                linked_job_id = _extract_reply_job_id(req.reply_txt)
        if linked_job_id is None:
            return None
        return job_manager.resolve_fix_target_job(linked_job_id, project_name, req.chat_id)

    def _extract_fix_instruction(req: _Req) -> str | None:
        text = req.message.text.strip()
        tokens = text.split()
        if tokens and tokens[0].lower() == "/fix":
            if len(tokens) == 1:
                return None
            return text.split(maxsplit=1)[1]
        parsed = parser.parse_fix_instruction(text)
        return parsed.instruction if parsed is not None else None

    def _queue_fix_confirmation(req: _Req, fix_instruction: str, target_job: Job) -> dict[str, str]:
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
            message_id=req.update.message.message_id,
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
        confirmation_text = _format_fix_source_confirmation(fix_request, target_job)
        req.background_tasks.add_task(
            req.notifier.send_with_buttons,
            req.chat_id,
            confirmation_text,
            _natural_job_confirmation_buttons(),
        )
        return {"status": "ok"}

    def _handle_fix_intent(req: _Req) -> dict[str, str] | None:
        try:
            fix_instruction = _extract_fix_instruction(req)
        except CommandParseError as exc:
            req.background_tasks.add_task(req.notifier.send_text, req.chat_id, str(exc))
            return {"status": "ignored"}
        if fix_instruction is None:
            return None
        if not fix_instruction.strip():
            return None
        target_job = _resolve_fix_target_from_reply(req)
        if target_job is None:
            req.background_tasks.add_task(
                req.notifier.send_text,
                req.chat_id,
                _format_fix_requires_reply_message(),
            )
            return {"status": "ignored"}
        return _queue_fix_confirmation(req, fix_instruction.strip(), target_job)

    def _attach_session(request: JobRequest) -> None:
        if conversation_store is None or request.message_id is None:
            return
        session_id = conversation_store.resolve_or_create_session(
            request.project,
            request.chat_id,
            request.message_id,
            request.reply_to_message_id,
        )
        token = conversation_store.get_runner_resume_token(session_id, request.model.value)
        # Native resume needs a stable worktree (CLI sessions are cwd-scoped). A bound branch
        # guarantees the reply reuses the parent's worktree; otherwise resuming could target a
        # missing session, so only establish a brand-new session and fall back to context
        # injection for the rest.
        if request.branch is not None:
            request.session_id = session_id
            request.resume_session_token = token
        elif token is None:
            request.session_id = session_id
            request.resume_session_token = None

    def _persist_session_token(final_job: Job) -> None:
        if (
            conversation_store is None
            or final_job.request.session_id is None
            or final_job.runner_session_id is None
        ):
            return
        conversation_store.set_runner_resume_token(
            final_job.request.session_id,
            final_job.request.model.value,
            final_job.runner_session_id,
        )

    def _submit_confirmed_fix_request(
        request: JobRequest,
        original_text: str,
        background_tasks: BackgroundTasks,
    ) -> None:
        if conversation_store is not None:
            conversation_store.append(
                project=request.project,
                chat_id=request.chat_id,
                role="user",
                text=original_text,
                message_id=request.message_id,
                reply_to_message_id=request.reply_to_message_id,
            )
            _cmdlog.info(
                "conversation fix user message recorded message_id=%s",
                request.message_id,
                chat_id=request.chat_id,
                user_id=request.requested_by,
                project=request.project,
            )

        _attach_session(request)

        def run_and_record_fix() -> None:
            final_job = job_manager.execute_fix_job(request)
            _persist_session_token(final_job)
            _cmdlog.info(
                "fix background run finished status=%s",
                final_job.status.value,
                chat_id=final_job.request.chat_id,
                user_id=final_job.request.requested_by,
                project=final_job.request.project,
                job_id=final_job.id,
            )
            if conversation_store is None:
                return
            conversation_store.append(
                project=final_job.request.project,
                chat_id=final_job.request.chat_id,
                role="job_accepted",
                text=f"Job accepted: {final_job.id}",
                job_id=final_job.id,
                message_id=final_job.accepted_message_id,
            )
            summary = format_job_result_memory_summary(final_job)
            conversation_store.append(
                project=final_job.request.project,
                chat_id=final_job.request.chat_id,
                role="job_result",
                text=summary,
                job_id=final_job.id,
                message_id=(
                    final_job.result_message_ids[0] if final_job.result_message_ids else None
                ),
            )
            if final_job.request.message_id is not None and final_job.branch is not None:
                conversation_store.bind_message_branch(
                    project=final_job.request.project,
                    chat_id=final_job.request.chat_id,
                    message_id=final_job.request.message_id,
                    branch=final_job.branch,
                    job_id=final_job.id,
                )

        background_tasks.add_task(run_and_record_fix)

    def _handle_pending(req: _Req, pending: PendingConfirmation | None) -> dict[str, str] | None:
        if pending is None:
            return None
        cc = req.command_context
        scope_project = req.scope_project
        chat_id = req.chat_id
        notifier = req.notifier
        bt = req.background_tasks

        if pending.command_name == _NATURAL_JOB_CONFIRMATION and req.message_head_lower != "/init":
            # Confirmation is button-only (Yes/No); a new parseable message replaces the pending one.
            try:
                parsed_request = parser.parse_natural(
                    req.message.text,
                    scope_project,
                    chat_id=chat_id,
                    user_id=req.user_id,
                    message_id=req.update.message.message_id,
                    reply_to_message_id=req.reply_mid,
                    reply_to_text=req.reply_txt,
                )
            except CommandParseError as exc:
                cc.confirmation_store.pop(scope_project, chat_id)
                _cmdlog.warning(
                    "parse error replacing pending message_id=%s err=%s",
                    req.update.message.message_id,
                    str(exc)[:120],
                    chat_id=chat_id,
                    user_id=req.user_id,
                )
                bt.add_task(notifier.send_text, chat_id, _format_natural_job_cancelled(pending.job_request))
                bt.add_task(notifier.send_text, chat_id, str(exc))
                return {"status": "ignored"}
            cc.confirmation_store.pop(scope_project, chat_id)
            _cmdlog.info(
                "natural pending replaced mode=%s model=%s branch=%s commit=%s instruction_len=%d reply_to=%s",
                parsed_request.mode.value,
                parsed_request.model.value,
                parsed_request.branch or "-",
                parsed_request.commit,
                len(parsed_request.instruction),
                parsed_request.reply_to_message_id or "-",
                chat_id=chat_id,
                user_id=req.user_id,
                project=parsed_request.project,
            )
            if _queue_natural_confirmation(req, parsed_request, req.message.text.strip()):
                return {"status": "ok"}
            return {"status": "ignored"}

        if pending.command_name == _NATURAL_JOB_MODE_INPUT and req.message_head_lower != "/init":
            cc.confirmation_store.pop(scope_project, chat_id)
            mode_prefix = "/plan" if pending.action == JobMode.PLAN.value else "/ask"
            try:
                parsed_request = parser.parse_natural(
                    f"{mode_prefix} {req.message.text}",
                    scope_project,
                    chat_id=chat_id,
                    user_id=req.user_id,
                    message_id=req.update.message.message_id,
                    reply_to_message_id=req.reply_mid,
                    reply_to_text=req.reply_txt,
                )
            except CommandParseError as exc:
                _cmdlog.warning(
                    "parse error for pending mode input message_id=%s mode=%s err=%s",
                    req.update.message.message_id,
                    pending.action,
                    str(exc)[:120],
                    chat_id=chat_id,
                    user_id=req.user_id,
                )
                bt.add_task(notifier.send_text, chat_id, str(exc))
                return {"status": "ignored"}
            _cmdlog.info(
                "pending mode input parsed mode=%s model=%s instruction_len=%d reply_to=%s",
                parsed_request.mode.value,
                parsed_request.model.value,
                len(parsed_request.instruction),
                parsed_request.reply_to_message_id or "-",
                chat_id=chat_id,
                user_id=req.user_id,
                project=parsed_request.project,
            )
            if _queue_natural_confirmation(req, parsed_request, req.message.text.strip()):
                return {"status": "ok"}
            return {"status": "ignored"}

        if (
            pending.command_name == "/fix"
            and pending.action == FIX_SOURCE_AWAIT_ACTION
            and req.message_head_lower != "/init"
            and not req.message.text.strip().startswith("/")
        ):
            cc.confirmation_store.pop(scope_project, chat_id)
            project_name = effective_project_name_for_chat(cc, chat_id)
            target_job = (
                job_manager.resolve_fix_target_job(pending.target_job_id, project_name, chat_id)
                if pending.target_job_id is not None and project_name is not None
                else None
            )
            if target_job is None:
                bt.add_task(notifier.send_text, chat_id, "Fix target job is no longer available.")
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
                chat_id=chat_id,
                requested_by=req.user_id,
                message_id=req.update.message.message_id,
                reply_to_message_id=pending.reply_to_message_id or req.reply_mid,
            )
            cc.confirmation_store.set(
                scope_project,
                chat_id,
                PendingConfirmation(
                    command_name="/fix",
                    action=FIX_SOURCE_PENDING_ACTION,
                    job_request=fix_request,
                    original_text=req.message.text.strip(),
                    target_job_id=target_job.id,
                ),
            )
            confirmation_text = _format_fix_source_confirmation(fix_request, target_job)
            bt.add_task(
                notifier.send_with_buttons,
                chat_id,
                confirmation_text,
                _natural_job_confirmation_buttons(),
            )
            return {"status": "ok"}

        if (
            pending.command_name == "/fix"
            and pending.action == FIX_SOURCE_PENDING_ACTION
            and req.message_head_lower != "/init"
        ):
            # Confirmation is button-only (Yes/No); any typed message cancels the pending fix.
            cc.confirmation_store.pop(scope_project, chat_id)
            bt.add_task(notifier.send_text, chat_id, "Cancelled the fix job.")
            return {"status": "ignored"}

        return None

    def _handle_command(req: _Req) -> dict[str, str] | None:
        command_response: CommandResponse | None = command_registry.dispatch_rich(
            req.message, req.command_context
        )
        if not command_response:
            return None
        raw_cmd = req.message.text.strip()
        cmd_token = raw_cmd.split(maxsplit=1)[0] if raw_cmd else ""
        _cmdlog.info(
            "command handled cmd=%s response_len=%d button_rows=%d",
            cmd_token,
            len(command_response.text),
            len(command_response.inline_buttons or []),
            chat_id=req.chat_id,
            user_id=req.user_id,
        )
        if command_response.inline_buttons:
            req.background_tasks.add_task(
                partial(
                    req.notifier.send_with_buttons,
                    req.chat_id,
                    command_response.text,
                    command_response.inline_buttons,
                    skip_body_i18n=command_response.skip_notifier_body_i18n,
                )
            )
        else:
            req.background_tasks.add_task(
                partial(
                    req.notifier.send_text,
                    req.chat_id,
                    command_response.text,
                    skip_body_i18n=command_response.skip_notifier_body_i18n,
                )
            )
        return {"status": "ok"}

    def _handle_natural(req: _Req) -> dict[str, str]:
        try:
            request = parser.parse_natural(
                req.message.text,
                req.scope_project,
                chat_id=req.chat_id,
                user_id=req.user_id,
                message_id=req.update.message.message_id,
                reply_to_message_id=req.reply_mid,
                reply_to_text=req.reply_txt,
            )
        except CommandParseError as exc:
            _cmdlog.warning(
                "parse error message_id=%s err=%s",
                req.update.message.message_id,
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

        if _queue_natural_confirmation(req, request, req.message.text.strip()):
            return {"status": "ok"}
        return {"status": "ignored"}

    @router.post("/webhook/{token_hash}")
    def telegram_webhook(
        token_hash: str,
        update: TelegramUpdate,
        background_tasks: BackgroundTasks,
        x_telegram_bot_api_secret_token: str | None = Header(default=None),
    ) -> dict[str, str]:
        route_key = normalize_webhook_token_hash_path_segment(token_hash)
        if route_key is None:
            raise HTTPException(status_code=404, detail="bot instance not found")
        bot_instance = bot_instance_manager.get(route_key)
        if bot_instance is None:
            raise HTTPException(status_code=404, detail="bot instance not found")
        auth_service = bot_instance.auth_service
        notifier = bot_instance.notifier
        command_context = replace(bot_instance.command_context, project_name=bot_instance.project_name)
        scope_project = bot_instance.project_name
        webhook_secret = bot_instance.webhook_secret

        _inbound.info("update received id=%s", update.update_id)
        if webhook_secret and x_telegram_bot_api_secret_token != webhook_secret:
            _authlog.warning("webhook secret mismatch update_id=%s", update.update_id)
            return {"status": "ignored"}

        if recent_updates.mark_seen(route_key, update.update_id):
            _inbound.info("duplicate update ignored id=%s", update.update_id)
            if update.callback_query:
                background_tasks.add_task(notifier.answer_callback_query, update.callback_query.id)
            return {"status": "ignored"}

        if update.callback_query:
            return _handle_callback_query(
                update,
                update.callback_query,
                notifier,
                auth_service,
                command_context,
                scope_project,
                background_tasks,
            )

        if not update.message:
            _inbound.info("update without message skipped update_id=%s", update.update_id)
            return {"status": "ignored"}
        if not update.message.text:
            chat_only = update.message.chat.id
            user_only = update.message.from_user.id if update.message.from_user else None
            _inbound.info(
                "empty text skipped update_id=%s message_id=%s",
                update.update_id,
                update.message.message_id,
                chat_id=chat_only,
                user_id=user_only,
            )
            return {"status": "ignored"}

        chat_id = update.message.chat.id
        user_id = update.message.from_user.id if update.message.from_user else None
        preview = _telegram_text_preview(update.message.text)
        _inbound.info(
            "message received update_id=%s message_id=%s len=%d reply_to=%s preview=%s",
            update.update_id,
            update.message.message_id,
            len(update.message.text),
            (
                update.message.reply_to_message.message_id
                if update.message.reply_to_message is not None
                else "-"
            ),
            preview or "(empty)",
            chat_id=chat_id,
            user_id=user_id,
        )
        if not auth_service.is_allowed(chat_id=chat_id, user_id=user_id):
            _authlog.warning(
                "unauthorized chat/user update_id=%s message_id=%s",
                update.update_id,
                update.message.message_id,
                chat_id=chat_id,
                user_id=user_id,
            )
            return {"status": "ignored"}

        message = TelegramMessage(chat_id=chat_id, user_id=user_id, text=update.message.text)
        message_tokens = message.text.strip().split(maxsplit=1)
        message_head_lower = (message_tokens[0] if message_tokens else "").lower()
        reply_mid = (
            update.message.reply_to_message.message_id
            if update.message.reply_to_message is not None
            else None
        )
        reply_txt = (
            update.message.reply_to_message.text
            if update.message.reply_to_message is not None
            else None
        )
        req = _Req(
            update=update,
            background_tasks=background_tasks,
            notifier=notifier,
            command_context=command_context,
            scope_project=scope_project,
            chat_id=chat_id,
            user_id=user_id,
            message=message,
            message_head_lower=message_head_lower,
            reply_mid=reply_mid,
            reply_txt=reply_txt,
        )

        pending = command_context.confirmation_store.get(scope_project, chat_id)
        pending_result = _handle_pending(req, pending)
        if pending_result is not None:
            return pending_result

        if message_head_lower in {"/plan", "/ask"} and len(message_tokens) == 1:
            mode = JobMode.PLAN if message_head_lower == "/plan" else JobMode.ASK
            command_context.confirmation_store.set(
                scope_project,
                chat_id,
                PendingConfirmation(
                    command_name=_NATURAL_JOB_MODE_INPUT,
                    action=mode.value,
                ),
            )
            background_tasks.add_task(notifier.send_text, chat_id, _format_mode_input_prompt(mode))
            return {"status": "ok"}

        if message_head_lower == "/fix" and len(message_tokens) == 1:
            target_job = _resolve_fix_target_from_reply(req)
            if target_job is None:
                background_tasks.add_task(
                    notifier.send_text, chat_id, _format_fix_requires_reply_message()
                )
                return {"status": "ignored"}
            command_context.confirmation_store.set(
                scope_project,
                chat_id,
                PendingConfirmation(
                    command_name="/fix",
                    action=FIX_SOURCE_AWAIT_ACTION,
                    target_job_id=target_job.id,
                    reply_to_message_id=reply_mid,
                ),
            )
            background_tasks.add_task(notifier.send_text, chat_id, _format_fix_mode_input_prompt())
            return {"status": "ok"}

        fix_intent_result = _handle_fix_intent(req)
        if fix_intent_result is not None:
            return fix_intent_result

        command_result = _handle_command(req)
        if command_result is not None:
            return command_result

        return _handle_natural(req)

    def _submit_confirmed_natural_request(
        request: JobRequest,
        original_text: str,
        background_tasks: BackgroundTasks,
    ) -> Job:
        if conversation_store is not None:
            conversation_store.append(
                project=request.project,
                chat_id=request.chat_id,
                role="user",
                text=original_text,
                message_id=request.message_id,
                reply_to_message_id=request.reply_to_message_id,
            )
            _cmdlog.info(
                "conversation user message recorded message_id=%s",
                request.message_id,
                chat_id=request.chat_id,
                user_id=request.requested_by,
                project=request.project,
            )

        _attach_session(request)
        job = job_manager.submit(request)
        _cmdlog.info(
            "job accepted background scheduled",
            chat_id=request.chat_id,
            user_id=request.requested_by,
            project=request.project,
            job_id=job.id,
        )

        if conversation_store is not None and request.message_id is not None:
            conversation_store.bind_user_message_job(
                project=request.project,
                chat_id=request.chat_id,
                message_id=request.message_id,
                job_id=job.id,
            )

        if (
            conversation_store is not None
            and request.message_id is not None
            and request.branch is not None
        ):
            conversation_store.bind_message_branch(
                project=request.project,
                chat_id=request.chat_id,
                message_id=request.message_id,
                branch=request.branch,
                job_id=job.id,
            )

        if conversation_store is not None:
            conversation_store.append(
                project=request.project,
                chat_id=request.chat_id,
                role="job_accepted",
                text=f"Job accepted: {job.id}",
                job_id=job.id,
                message_id=getattr(job, "accepted_message_id", None),
            )
            _cmdlog.info(
                "conversation job_accepted recorded",
                chat_id=request.chat_id,
                user_id=request.requested_by,
                project=request.project,
                job_id=job.id,
            )

        if conversation_store is not None:

            def run_and_record(jid: str) -> None:
                _cmdlog.info("background job run start", job_id=jid)
                final_job = job_manager.run(jid)
                if final_job is None:
                    _cmdlog.warning("background job run returned none", job_id=jid)
                    return
                _persist_session_token(final_job)
                summary = format_job_result_memory_summary(final_job)
                conversation_store.append(
                    project=final_job.request.project,
                    chat_id=final_job.request.chat_id,
                    role="job_result",
                    text=summary,
                    job_id=final_job.id,
                    message_id=(
                        final_job.result_message_ids[0]
                        if final_job.result_message_ids
                        else None
                    ),
                )
                _cmdlog.info(
                    "conversation job_result recorded status=%s",
                    final_job.status.value,
                    chat_id=final_job.request.chat_id,
                    user_id=final_job.request.requested_by,
                    project=final_job.request.project,
                    job_id=final_job.id,
                )
                if final_job.request.message_id is not None and final_job.branch is not None:
                    conversation_store.bind_message_branch(
                        project=final_job.request.project,
                        chat_id=final_job.request.chat_id,
                        message_id=final_job.request.message_id,
                        branch=final_job.branch,
                        job_id=final_job.id,
                    )
                    _cmdlog.info(
                        "conversation branch binding recorded branch=%s",
                        final_job.branch,
                        chat_id=final_job.request.chat_id,
                        user_id=final_job.request.requested_by,
                        project=final_job.request.project,
                        job_id=final_job.id,
                    )

            background_tasks.add_task(run_and_record, job.id)
        else:
            background_tasks.add_task(job_manager.run, job.id)
        _ = job_store
        return job

    return router
