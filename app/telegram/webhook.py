from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Header
from pydantic import BaseModel, Field

from app.jobs.manager import JobManager
from app.jobs.store import InMemoryJobStore
from app.security.auth import AllowlistAuthService
from app.telegram.commands import CommandContext, CommandRegistry, TelegramMessage
from app.telegram.parser import CommandParser


class TelegramChat(BaseModel):
    id: int


class TelegramUser(BaseModel):
    id: int


class TelegramIncomingMessage(BaseModel):
    message_id: int | None = None
    text: str | None = None
    chat: TelegramChat
    from_user: TelegramUser | None = Field(default=None, alias="from")

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
    webhook_secret: str | None = None,
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
            return {"status": "ok", "message": command_response}

        request = parser.parse_natural(message.text, chat_id=chat_id, user_id=user_id)
        job = job_manager.submit(request)
        background_tasks.add_task(job_manager.run, job.id)
        _ = job_store
        return {"status": "accepted", "job_id": job.id}

    return router
