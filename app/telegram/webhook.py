from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Header
from pydantic import BaseModel, Field

from app.jobs.manager import JobManager
from app.jobs.store import InMemoryJobStore
from app.monitoring.events import EventLogger
from app.security.auth import AllowlistAuthService
from app.telegram.commands import CommandContext, CommandRegistry, CommandResponse, TelegramMessage
from app.telegram.conversation import SQLiteConversationStore
from app.telegram.notifier import TelegramNotifier
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


class TelegramChat(BaseModel):
    id: int


class TelegramUser(BaseModel):
    id: int


class TelegramReplyMessage(BaseModel):
    message_id: int


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
    auth_service: AllowlistAuthService,
    parser: CommandParser,
    command_registry: CommandRegistry,
    command_context: CommandContext,
    job_manager: JobManager,
    job_store: InMemoryJobStore,
    notifier: TelegramNotifier,
    webhook_secret: str | None = None,
    conversation_store: SQLiteConversationStore | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/telegram", tags=["telegram"])

    @router.post("/webhook")
    def telegram_webhook(
        update: TelegramUpdate,
        background_tasks: BackgroundTasks,
        x_telegram_bot_api_secret_token: str | None = Header(default=None),
    ) -> dict[str, str]:
        if webhook_secret and x_telegram_bot_api_secret_token != webhook_secret:
            _authlog.warning("webhook secret mismatch")
            return {"status": "ignored"}

        if update.callback_query:
            cq = update.callback_query
            if cq.message is None or not cq.data:
                background_tasks.add_task(notifier.answer_callback_query, cq.id)
                return {"status": "ignored"}
            cq_chat_id = cq.message.chat.id
            cq_user_id = cq.from_user.id
            if not auth_service.is_allowed(chat_id=cq_chat_id, user_id=cq_user_id):
                _authlog.warning("unauthorized callback_query", chat_id=cq_chat_id, user_id=cq_user_id)
                background_tasks.add_task(notifier.answer_callback_query, cq.id)
                return {"status": "ignored"}
            cq_message = TelegramMessage(chat_id=cq_chat_id, user_id=cq_user_id, text=cq.data)
            cq_response = command_registry.dispatch_rich(cq_message, command_context)
            background_tasks.add_task(notifier.answer_callback_query, cq.id)
            if cq_response:
                _cmdlog.info("callback_query handled: %s", cq.data, chat_id=cq_chat_id, user_id=cq_user_id)
                if cq_response.inline_buttons:
                    background_tasks.add_task(
                        notifier.send_with_buttons,
                        cq_chat_id,
                        cq_response.text,
                        cq_response.inline_buttons,
                    )
                else:
                    background_tasks.add_task(notifier.send_text, cq_chat_id, cq_response.text)
            return {"status": "ok"}

        if not update.message:
            _inbound.info("update without message skipped")
            return {"status": "ignored"}
        if not update.message.text:
            chat_only = update.message.chat.id
            user_only = update.message.from_user.id if update.message.from_user else None
            _inbound.info("empty text skipped", chat_id=chat_only, user_id=user_only)
            return {"status": "ignored"}

        chat_id = update.message.chat.id
        user_id = update.message.from_user.id if update.message.from_user else None
        preview = _telegram_text_preview(update.message.text)
        _inbound.info("received: %s", preview or "(empty)", chat_id=chat_id, user_id=user_id)
        if not auth_service.is_allowed(chat_id=chat_id, user_id=user_id):
            _authlog.warning("unauthorized chat/user", chat_id=chat_id, user_id=user_id)
            return {"status": "ignored"}

        message = TelegramMessage(chat_id=chat_id, user_id=user_id, text=update.message.text)
        command_response: CommandResponse | None = command_registry.dispatch_rich(message, command_context)
        if command_response:
            raw_cmd = message.text.strip()
            cmd_token = raw_cmd.split(maxsplit=1)[0] if raw_cmd else ""
            _cmdlog.info("command handled: %s", cmd_token, chat_id=chat_id, user_id=user_id)
            if command_response.inline_buttons:
                background_tasks.add_task(
                    notifier.send_with_buttons,
                    chat_id,
                    command_response.text,
                    command_response.inline_buttons,
                )
            else:
                background_tasks.add_task(notifier.send_text, chat_id, command_response.text)
            return {"status": "ok"}

        try:
            request = parser.parse_natural(
                message.text,
                chat_id=chat_id,
                user_id=user_id,
                message_id=update.message.message_id,
                reply_to_message_id=(
                    update.message.reply_to_message.message_id
                    if update.message.reply_to_message is not None
                    else None
                ),
            )
        except CommandParseError as exc:
            _cmdlog.warning("parse error: %s", str(exc)[:120], chat_id=chat_id, user_id=user_id)
            background_tasks.add_task(notifier.send_text, chat_id, str(exc))
            return {"status": "ignored"}

        if conversation_store is not None:
            conversation_store.append(
                project=request.project,
                chat_id=chat_id,
                role="user",
                text=message.text.strip(),
                message_id=update.message.message_id,
                reply_to_message_id=(
                    update.message.reply_to_message.message_id
                    if update.message.reply_to_message is not None
                    else None
                ),
            )

        job = job_manager.submit(request)
        _cmdlog.info(
            "job accepted",
            chat_id=chat_id,
            user_id=user_id,
            project=request.project,
            job_id=job.id,
        )

        if (
            conversation_store is not None
            and request.message_id is not None
            and request.branch is not None
        ):
            conversation_store.bind_message_branch(
                project=request.project,
                chat_id=chat_id,
                message_id=request.message_id,
                branch=request.branch,
                job_id=job.id,
            )

        if conversation_store is not None:
            conversation_store.append(
                project=request.project,
                chat_id=chat_id,
                role="job_accepted",
                text=f"Job 접수: {job.id}",
                job_id=job.id,
            )

        if conversation_store is not None:

            def run_and_record(jid: str) -> None:
                final_job = job_manager.run(jid)
                if final_job is None:
                    return
                summary = f"status={final_job.status.value}"
                if final_job.error_stage:
                    summary += f" stage={final_job.error_stage}"
                if final_job.error:
                    summary += f" err={str(final_job.error)[:300]}"
                conversation_store.append(
                    project=final_job.request.project,
                    chat_id=final_job.request.chat_id,
                    role="job_result",
                    text=summary,
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

            background_tasks.add_task(run_and_record, job.id)
        else:
            background_tasks.add_task(job_manager.run, job.id)
        _ = job_store
        return {"status": "accepted", "job_id": job.id}

    return router
