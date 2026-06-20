from __future__ import annotations

import hmac
from collections.abc import Callable
from dataclasses import replace

from fastapi import BackgroundTasks, HTTPException

from app.jobs.schemas import JobMode
from app.monitoring.events import EventLogger
from app.projects.registry import normalize_webhook_token_hash_path_segment
from app.telegram.bot_instances import BotInstanceManager
from app.telegram.confirmations import PendingConfirmation
from app.telegram.handlers.callback_dispatcher import telegram_text_preview
from app.telegram.handlers.fix_flow import FixFlow
from app.telegram.handlers.natural_flow import NaturalFlow
from app.telegram.handlers.request import TelegramCallbackQuery, TelegramUpdate, WebhookRequest
from app.telegram.commands import CommandContext, TelegramMessage
from app.telegram.notifier import Notifier
from app.security.auth import AllowlistAuthService

_inbound = EventLogger("app.telegram.inbound", "telegram.inbound")
_authlog = EventLogger("app.security.auth", "auth.reject")


class WebhookUpdateHandler:
    def __init__(
        self,
        *,
        bot_instance_manager: BotInstanceManager,
        recent_updates,
        plan_decision_store,
        handle_callback_query: Callable[
            [
                TelegramUpdate,
                TelegramCallbackQuery,
                Notifier,
                AllowlistAuthService,
                CommandContext,
                str | None,
                BackgroundTasks,
            ],
            dict[str, str],
        ],
        handle_pending: Callable[[WebhookRequest, PendingConfirmation | None], dict[str, str] | None],
        handle_fix_intent: Callable[[WebhookRequest], dict[str, str] | None],
        handle_command: Callable[[WebhookRequest], dict[str, str] | None],
        handle_natural: Callable[[WebhookRequest], dict[str, str]],
        natural_flow_factory: Callable[[], NaturalFlow],
        fix_flow_factory: Callable[[], FixFlow],
    ) -> None:
        self._bot_instance_manager = bot_instance_manager
        self._recent_updates = recent_updates
        self._plan_decision_store = plan_decision_store
        self._handle_callback_query = handle_callback_query
        self._handle_pending = handle_pending
        self._handle_fix_intent = handle_fix_intent
        self._handle_command = handle_command
        self._handle_natural = handle_natural
        self._natural_flow_factory = natural_flow_factory
        self._fix_flow_factory = fix_flow_factory

    def handle(
        self,
        token_hash: str,
        update: TelegramUpdate,
        background_tasks: BackgroundTasks,
        webhook_secret_header: str | None,
    ) -> dict[str, str]:
        route_key = normalize_webhook_token_hash_path_segment(token_hash)
        if route_key is None:
            raise HTTPException(status_code=404, detail="bot instance not found")
        bot_instance = self._bot_instance_manager.get(route_key)
        if bot_instance is None:
            raise HTTPException(status_code=404, detail="bot instance not found")
        auth_service = bot_instance.auth_service
        notifier = bot_instance.notifier
        command_context = replace(bot_instance.command_context, project_name=bot_instance.project_name)
        scope_project = bot_instance.project_name
        webhook_secret = bot_instance.webhook_secret

        _inbound.info("update received id=%s", update.update_id)
        if webhook_secret and not hmac.compare_digest(webhook_secret_header or "", webhook_secret):
            _authlog.warning("webhook secret mismatch update_id=%s", update.update_id)
            return {"status": "ignored"}

        if self._recent_updates.mark_seen(route_key, update.update_id):
            _inbound.info("duplicate update ignored id=%s", update.update_id)
            if update.callback_query:
                background_tasks.add_task(notifier.answer_callback_query, update.callback_query.id)
            return {"status": "ignored"}

        if update.callback_query:
            return self._handle_callback_query(
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
        preview = telegram_text_preview(update.message.text)
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
        req = WebhookRequest(
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

        if self._plan_decision_store.pop(scope_project, chat_id) is not None:
            # A typed message abandons an in-progress decision prompt (button-only flow).
            background_tasks.add_task(
                notifier.send_text, chat_id, "Cancelled the pending plan decision."
            )

        pending = command_context.confirmation_store.get(scope_project, chat_id)
        pending_result = self._handle_pending(req, pending)
        if pending_result is not None:
            return pending_result

        if message_head_lower in {"/plan", "/ask", "/research"} and len(message_tokens) == 1:
            mode_by_command = {
                "/plan": JobMode.PLAN,
                "/ask": JobMode.ASK,
                "/research": JobMode.RESEARCH,
            }
            mode = mode_by_command[message_head_lower]
            return self._natural_flow_factory().prompt_for_mode_instruction(req, mode)

        if message_head_lower == "/fix" and len(message_tokens) == 1:
            return self._fix_flow_factory().prompt_for_instruction(req)

        fix_intent_result = self._handle_fix_intent(req)
        if fix_intent_result is not None:
            return fix_intent_result

        command_result = self._handle_command(req)
        if command_result is not None:
            return command_result

        return self._handle_natural(req)
