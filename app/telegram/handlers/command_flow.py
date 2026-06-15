from __future__ import annotations

from functools import partial

from app.monitoring.events import EventLogger
from app.telegram.commands import CommandRegistry, CommandResponse
from app.telegram.handlers.request import WebhookRequest

_cmdlog = EventLogger("app.telegram.command", "telegram.command")


class CommandFlow:
    def __init__(self, *, command_registry: CommandRegistry) -> None:
        self._command_registry = command_registry

    def handle_command(self, req: WebhookRequest) -> dict[str, str] | None:
        command_response: CommandResponse | None = self._command_registry.dispatch_rich(
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
                    req.notifier.send_long_text,
                    req.chat_id,
                    command_response.text,
                    skip_body_i18n=command_response.skip_notifier_body_i18n,
                )
            )
        return {"status": "ok"}
