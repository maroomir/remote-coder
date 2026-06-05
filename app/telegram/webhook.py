from __future__ import annotations

import re
from collections import deque
from dataclasses import replace
from functools import partial
from threading import Lock

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException
from pydantic import BaseModel, Field

from app.ai.usage import format_token_usage
from app.jobs.manager import JobManager
from app.jobs.schemas import FixKind, Job, JobMode, JobRequest
from app.jobs.store import JobStore
from app.monitoring.events import EventLogger
from app.telegram.commands import (
    CommandContext,
    CommandRegistry,
    CommandResponse,
    FIX_COMMIT_PENDING_ACTION,
    FIX_SOURCE_AWAIT_ACTION,
    FIX_SOURCE_PENDING_ACTION,
    InlineButton,
    TelegramMessage,
    effective_project_name_for_chat,
)
from app.projects.registry import normalize_webhook_token_hash_path_segment
from app.telegram.bot_instances import BotInstanceManager
from app.telegram.confirmations import PendingConfirmation
from app.telegram.conversation import SQLiteConversationStore
from app.telegram.parser import CommandParseError, CommandParser

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
    summary += f" model={final_job.runner_actual_model or final_job.request.model.value}"
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
    *,
    use_buttons: bool = False,
) -> str:
    lines = [
        "Confirm the work to run.",
        "",
        f"- Project: {request.project}",
        f"- Work branch: {current_branch}",
        f"- Model: {request.model.value}",
    ]
    if request.mode is JobMode.PLAN:
        lines.append("- Mode: plan (read-only, no commit/push)")
    elif request.mode is JobMode.ASK:
        lines.append("- Mode: ask (read-only, no commit/push)")
    else:
        lines.append("- Mode: agent (may edit code, commit, and push)")
    if request.branch:
        lines.append(f"- Requested branch: {request.branch}")
    if use_buttons:
        footer = "Choose whether to run it."
    else:
        footer = (
            "Send `y` or `Y` to run it. "
            "A new natural-language request can replace this confirmation. "
            "Unparsed input cancels the pending work."
        )
    lines.extend(["", footer])
    return "\n".join(lines)


_FIX_REPLY_PREFIX_RE = re.compile(r"^(?:fix|수정)\s*[:：]\s*", re.IGNORECASE)


def _match_fix_reply_prefix(text: str) -> str | None:
    stripped = text.lstrip()
    match = _FIX_REPLY_PREFIX_RE.match(stripped)
    if match is None:
        return None
    return stripped[match.end() :]


def _format_fix_source_confirmation(
    request: JobRequest,
    target_job: Job,
    *,
    use_buttons: bool,
) -> str:
    lines = [
        "수정 작업을 확인하세요.",
        "",
        f"- Project: {request.project}",
        f"- 대상 Job: {target_job.id}",
        f"- 브랜치: {target_job.branch}",
        f"- 원본 커밋: {target_job.commit_hash}",
        f"- Model: {request.model.value}",
        "- Mode: agent_fix (source) — 기존 커밋을 amend 후 --force-with-lease push",
    ]
    if use_buttons:
        lines.extend(["", "Choose whether to run it."])
    else:
        lines.extend(
            [
                "",
                "Send `y` or `Y` to run it. Any other response cancels it.",
            ]
        )
    return "\n".join(lines)


def _natural_job_confirmation_buttons() -> list[list[InlineButton]]:
    return [[InlineButton("Yes", _NATURAL_JOB_CONFIRM_YES), InlineButton("No", _NATURAL_JOB_CONFIRM_NO)]]


def _natural_job_confirmation_buttons_enabled(command_context: CommandContext) -> bool:
    if command_context.advanced_settings_store is None:
        return False
    return command_context.advanced_settings_store.get().natural_job_confirmation_buttons_enabled


def _format_natural_job_cancelled(request: JobRequest | None) -> str:
    if request is None:
        return "Cancelled the work request."
    return f"Cancelled the work request. (project: {request.project}, model: {request.model.value})"


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
            cq = update.callback_query
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
            notifier.answer_callback_query(cq.id)
            if cq.data in {_NATURAL_JOB_CONFIRM_YES, _NATURAL_JOB_CONFIRM_NO}:
                pending = command_context.confirmation_store.get(scope_project, cq_chat_id)
                if pending is None or pending.command_name != _NATURAL_JOB_CONFIRMATION:
                    background_tasks.add_task(notifier.send_text, cq_chat_id, "확인 대기 작업이 없습니다.")
                    return {"status": "ignored"}
                confirmed = command_context.confirmation_store.pop(scope_project, cq_chat_id)
                if cq.data == _NATURAL_JOB_CONFIRM_NO:
                    background_tasks.add_task(
                        notifier.send_text,
                        cq_chat_id,
                        _format_natural_job_cancelled(confirmed.job_request if confirmed else None),
                    )
                    return {"status": "ok"}
                if confirmed is None or confirmed.job_request is None or confirmed.original_text is None:
                    background_tasks.add_task(notifier.send_text, cq_chat_id, "확인 대기 작업을 처리할 수 없습니다.")
                    return {"status": "ignored"}
                job = _submit_confirmed_natural_request(
                    request=confirmed.job_request,
                    original_text=confirmed.original_text,
                    background_tasks=background_tasks,
                )
                return {"status": "accepted", "job_id": job.id}
            cq_message = TelegramMessage(chat_id=cq_chat_id, user_id=cq_user_id, text=cq.data)
            cq_response = command_registry.dispatch_rich(cq_message, command_context)
            if cq_response:
                button_rows = len(cq_response.inline_buttons or [])
                _cmdlog.info(
                    "callback_query handled cmd=%s response_len=%d button_rows=%d",
                    cq_preview or "(empty)",
                    len(cq_response.text),
                    button_rows,
                    chat_id=cq_chat_id,
                    user_id=cq_user_id,
                )
                if cq_response.inline_buttons:
                    background_tasks.add_task(
                        partial(
                            notifier.send_with_buttons,
                            cq_chat_id,
                            cq_response.text,
                            cq_response.inline_buttons,
                            skip_body_i18n=cq_response.skip_notifier_body_i18n,
                        )
                    )
                else:
                    background_tasks.add_task(
                        partial(
                            notifier.send_text,
                            cq_chat_id,
                            cq_response.text,
                            skip_body_i18n=cq_response.skip_notifier_body_i18n,
                        )
                    )
            else:
                _cmdlog.info(
                    "callback_query no command response cmd=%s",
                    cq_preview or "(empty)",
                    chat_id=cq_chat_id,
                    user_id=cq_user_id,
                )
            return {"status": "ok"}

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
        pending = command_context.confirmation_store.get(scope_project, chat_id)
        message_tokens = message.text.strip().split(maxsplit=1)
        message_head = message_tokens[0] if message_tokens else ""
        message_head_lower = message_head.lower()

        def _queue_natural_confirmation(req: JobRequest, original_text_stripped: str) -> bool:
            ent = command_context.project_registry.get(bot_instance.project_name)
            if ent is None:
                background_tasks.add_task(
                    notifier.send_text,
                    chat_id,
                    f"Unknown project: {bot_instance.project_name}",
                )
                return False
            try:
                current_branch = str(command_context.git_service.get_current_branch(ent.root_path))
            except RuntimeError as exc:
                background_tasks.add_task(notifier.send_text, chat_id, f"Could not resolve work branch: {exc}")
                return False
            command_context.confirmation_store.set(
                scope_project,
                chat_id,
                PendingConfirmation(
                    command_name=_NATURAL_JOB_CONFIRMATION,
                    action="submit",
                    job_request=req,
                    original_text=original_text_stripped,
                ),
            )
            use_confirmation_buttons = _natural_job_confirmation_buttons_enabled(command_context)
            confirmation_text = _format_natural_job_confirmation(
                req,
                current_branch,
                use_buttons=use_confirmation_buttons,
            )
            if use_confirmation_buttons:
                background_tasks.add_task(
                    notifier.send_with_buttons,
                    chat_id,
                    confirmation_text,
                    _natural_job_confirmation_buttons(),
                )
            else:
                background_tasks.add_task(notifier.send_text, chat_id, confirmation_text)
            return True

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

        if (
            pending is not None
            and pending.command_name == _NATURAL_JOB_CONFIRMATION
            and message_head_lower != "/init"
        ):
            if message.text.strip() in {"y", "Y"}:
                confirmed = command_context.confirmation_store.pop(scope_project, chat_id)
                if confirmed is None or confirmed.job_request is None or confirmed.original_text is None:
                    background_tasks.add_task(notifier.send_text, chat_id, "확인 대기 작업을 처리할 수 없습니다.")
                    return {"status": "ignored"}
                job = _submit_confirmed_natural_request(
                    request=confirmed.job_request,
                    original_text=confirmed.original_text,
                    background_tasks=background_tasks,
                )
                return {"status": "accepted", "job_id": job.id}
            try:
                parsed_request = parser.parse_natural(
                    message.text,
                    bot_instance.project_name,
                    chat_id=chat_id,
                    user_id=user_id,
                    message_id=update.message.message_id,
                    reply_to_message_id=reply_mid,
                    reply_to_text=reply_txt,
                )
            except CommandParseError as exc:
                command_context.confirmation_store.pop(scope_project, chat_id)
                _cmdlog.warning(
                    "parse error replacing pending message_id=%s err=%s",
                    update.message.message_id,
                    str(exc)[:120],
                    chat_id=chat_id,
                    user_id=user_id,
                )
                background_tasks.add_task(
                    notifier.send_text,
                    chat_id,
                    _format_natural_job_cancelled(pending.job_request),
                )
                background_tasks.add_task(notifier.send_text, chat_id, str(exc))
                return {"status": "ignored"}
            command_context.confirmation_store.pop(scope_project, chat_id)
            _cmdlog.info(
                "natural pending replaced mode=%s model=%s branch=%s commit=%s instruction_len=%d reply_to=%s",
                parsed_request.mode.value,
                parsed_request.model.value,
                parsed_request.branch or "-",
                parsed_request.commit,
                len(parsed_request.instruction),
                parsed_request.reply_to_message_id or "-",
                chat_id=chat_id,
                user_id=user_id,
                project=parsed_request.project,
            )
            if _queue_natural_confirmation(parsed_request, message.text.strip()):
                return {"status": "ok"}
            return {"status": "ignored"}

        if (
            pending is not None
            and pending.command_name == _NATURAL_JOB_MODE_INPUT
            and message_head_lower != "/init"
        ):
            command_context.confirmation_store.pop(scope_project, chat_id)
            mode_prefix = "/plan" if pending.action == JobMode.PLAN.value else "/ask"
            try:
                parsed_request = parser.parse_natural(
                    f"{mode_prefix} {message.text}",
                    bot_instance.project_name,
                    chat_id=chat_id,
                    user_id=user_id,
                    message_id=update.message.message_id,
                    reply_to_message_id=reply_mid,
                    reply_to_text=reply_txt,
                )
            except CommandParseError as exc:
                _cmdlog.warning(
                    "parse error for pending mode input message_id=%s mode=%s err=%s",
                    update.message.message_id,
                    pending.action,
                    str(exc)[:120],
                    chat_id=chat_id,
                    user_id=user_id,
                )
                background_tasks.add_task(notifier.send_text, chat_id, str(exc))
                return {"status": "ignored"}
            _cmdlog.info(
                "pending mode input parsed mode=%s model=%s instruction_len=%d reply_to=%s",
                parsed_request.mode.value,
                parsed_request.model.value,
                len(parsed_request.instruction),
                parsed_request.reply_to_message_id or "-",
                chat_id=chat_id,
                user_id=user_id,
                project=parsed_request.project,
            )
            if _queue_natural_confirmation(parsed_request, message.text.strip()):
                return {"status": "ok"}
            return {"status": "ignored"}

        if (
            pending is not None
            and pending.command_name == "/fix"
            and pending.action == FIX_SOURCE_AWAIT_ACTION
            and message_head_lower != "/init"
            and not message.text.strip().startswith("/")
        ):
            command_context.confirmation_store.pop(scope_project, chat_id)
            target_job = (
                job_store.get(pending.target_job_id)
                if pending.target_job_id is not None
                else None
            )
            project_name = effective_project_name_for_chat(command_context, chat_id)
            if (
                target_job is None
                or project_name is None
                or not job_manager.is_fix_candidate(target_job, project_name, chat_id)
            ):
                background_tasks.add_task(
                    notifier.send_text,
                    chat_id,
                    "수정 대상 Job을 더 이상 사용할 수 없습니다.",
                )
                return {"status": "ignored"}
            fix_request = JobRequest(
                project=project_name,
                model=target_job.request.model,
                instruction=message.text.strip(),
                mode=JobMode.AGENT_FIX,
                fix_kind=FixKind.SOURCE,
                parent_job_id=target_job.id,
                branch=target_job.branch,
                chat_id=chat_id,
                requested_by=user_id,
                message_id=update.message.message_id,
                reply_to_message_id=reply_mid,
            )
            command_context.confirmation_store.set(
                scope_project,
                chat_id,
                PendingConfirmation(
                    command_name="/fix",
                    action=FIX_SOURCE_PENDING_ACTION,
                    job_request=fix_request,
                    original_text=message.text.strip(),
                    target_job_id=target_job.id,
                ),
            )
            use_buttons = _natural_job_confirmation_buttons_enabled(command_context)
            confirmation_text = _format_fix_source_confirmation(
                fix_request, target_job, use_buttons=use_buttons
            )
            if use_buttons:
                background_tasks.add_task(
                    notifier.send_with_buttons,
                    chat_id,
                    confirmation_text,
                    _natural_job_confirmation_buttons(),
                )
            else:
                background_tasks.add_task(notifier.send_text, chat_id, confirmation_text)
            return {"status": "ok"}

        if (
            pending is not None
            and pending.command_name == "/fix"
            and pending.action == FIX_SOURCE_PENDING_ACTION
            and message_head_lower != "/init"
        ):
            if message.text.strip() in {"y", "Y"}:
                confirmed = command_context.confirmation_store.pop(scope_project, chat_id)
                if (
                    confirmed is None
                    or confirmed.job_request is None
                    or confirmed.job_request.parent_job_id is None
                ):
                    background_tasks.add_task(
                        notifier.send_text,
                        chat_id,
                        "확인 대기 작업을 처리할 수 없습니다.",
                    )
                    return {"status": "ignored"}
                background_tasks.add_task(
                    job_manager.execute_fix_job, confirmed.job_request, None
                )
                return {"status": "accepted"}
            command_context.confirmation_store.pop(scope_project, chat_id)
            background_tasks.add_task(
                notifier.send_text,
                chat_id,
                "수정 작업을 취소했습니다.",
            )
            return {"status": "ignored"}

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

        command_response: CommandResponse | None = command_registry.dispatch_rich(message, command_context)
        if command_response:
            raw_cmd = message.text.strip()
            cmd_token = raw_cmd.split(maxsplit=1)[0] if raw_cmd else ""
            _cmdlog.info(
                "command handled cmd=%s response_len=%d button_rows=%d",
                cmd_token,
                len(command_response.text),
                len(command_response.inline_buttons or []),
                chat_id=chat_id,
                user_id=user_id,
            )
            if command_response.inline_buttons:
                background_tasks.add_task(
                    partial(
                        notifier.send_with_buttons,
                        chat_id,
                        command_response.text,
                        command_response.inline_buttons,
                        skip_body_i18n=command_response.skip_notifier_body_i18n,
                    )
                )
            else:
                background_tasks.add_task(
                    partial(
                        notifier.send_text,
                        chat_id,
                        command_response.text,
                        skip_body_i18n=command_response.skip_notifier_body_i18n,
                    )
                )
            return {"status": "ok"}

        fix_reply_match = _match_fix_reply_prefix(message.text)
        if (
            fix_reply_match is not None
            and reply_mid is not None
            and conversation_store is not None
        ):
            fix_instruction = fix_reply_match.strip()
            project_name_for_fix = effective_project_name_for_chat(command_context, chat_id)
            linked_job_id = conversation_store.get_job_id_for_message_id(
                bot_instance.project_name, chat_id, reply_mid
            )
            target_job = job_store.get(linked_job_id) if linked_job_id else None
            if (
                fix_instruction
                and project_name_for_fix is not None
                and target_job is not None
                and job_manager.is_fix_candidate(target_job, project_name_for_fix, chat_id)
            ):
                fix_request = JobRequest(
                    project=project_name_for_fix,
                    model=target_job.request.model,
                    instruction=fix_instruction,
                    mode=JobMode.AGENT_FIX,
                    fix_kind=FixKind.SOURCE,
                    parent_job_id=target_job.id,
                    branch=target_job.branch,
                    chat_id=chat_id,
                    requested_by=user_id,
                    message_id=update.message.message_id,
                    reply_to_message_id=reply_mid,
                )
                command_context.confirmation_store.set(
                    scope_project,
                    chat_id,
                    PendingConfirmation(
                        command_name="/fix",
                        action=FIX_SOURCE_PENDING_ACTION,
                        job_request=fix_request,
                        original_text=message.text.strip(),
                        target_job_id=target_job.id,
                    ),
                )
                use_buttons = _natural_job_confirmation_buttons_enabled(command_context)
                confirmation_text = _format_fix_source_confirmation(
                    fix_request, target_job, use_buttons=use_buttons
                )
                if use_buttons:
                    background_tasks.add_task(
                        notifier.send_with_buttons,
                        chat_id,
                        confirmation_text,
                        _natural_job_confirmation_buttons(),
                    )
                else:
                    background_tasks.add_task(notifier.send_text, chat_id, confirmation_text)
                return {"status": "ok"}

        try:
            parsed_request = parser.parse_natural(
                message.text,
                bot_instance.project_name,
                chat_id=chat_id,
                user_id=user_id,
                message_id=update.message.message_id,
                reply_to_message_id=(
                    update.message.reply_to_message.message_id
                    if update.message.reply_to_message is not None
                    else None
                ),
                reply_to_text=(
                    update.message.reply_to_message.text
                    if update.message.reply_to_message is not None
                    else None
                ),
            )
        except CommandParseError as exc:
            _cmdlog.warning(
                "parse error message_id=%s err=%s",
                update.message.message_id,
                str(exc)[:120],
                chat_id=chat_id,
                user_id=user_id,
            )
            background_tasks.add_task(notifier.send_text, chat_id, str(exc))
            return {"status": "ignored"}
        request = parsed_request

        _cmdlog.info(
            "natural request parsed mode=%s model=%s branch=%s commit=%s instruction_len=%d reply_to=%s",
            request.mode.value,
            request.model.value,
            request.branch or "-",
            request.commit,
            len(request.instruction),
            request.reply_to_message_id or "-",
            chat_id=chat_id,
            user_id=user_id,
            project=request.project,
        )

        if _queue_natural_confirmation(request, message.text.strip()):
            return {"status": "ok"}
        return {"status": "ignored"}

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
                text=f"Job 접수: {job.id}",
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
