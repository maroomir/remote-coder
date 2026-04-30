from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Header
from pydantic import BaseModel, Field

from app.jobs.manager import JobManager
from app.jobs.store import InMemoryJobStore
from app.security.auth import AllowlistAuthService
from app.telegram.commands import CommandContext, CommandRegistry, TelegramMessage
from app.telegram.conversation import SQLiteConversationStore
from app.telegram.notifier import TelegramNotifier
from app.telegram.parser import CommandParseError, CommandParser


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


class TelegramUpdate(BaseModel):
    update_id: int
    message: TelegramIncomingMessage | None = None


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
            return {"status": "ignored"}
        if not update.message or not update.message.text:
            return {"status": "ignored"}

        chat_id = update.message.chat.id
        user_id = update.message.from_user.id if update.message.from_user else None
        if not auth_service.is_allowed(chat_id=chat_id, user_id=user_id):
            return {"status": "ignored"}

        message = TelegramMessage(chat_id=chat_id, user_id=user_id, text=update.message.text)
        command_response = command_registry.dispatch(message, command_context)
        if command_response:
            background_tasks.add_task(notifier.send_text, chat_id, command_response)
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
