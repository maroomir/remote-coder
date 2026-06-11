from __future__ import annotations

from dataclasses import dataclass

from fastapi import BackgroundTasks
from pydantic import BaseModel, Field

from app.telegram.commands import CommandContext, TelegramMessage
from app.telegram.notifier import Notifier


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
class WebhookRequest:
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
