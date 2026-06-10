from __future__ import annotations

from app.models import UiLanguage
from app.telegram.commands.base import (
    CommandContext,
    CommandResponse,
    ConfirmableCommand,
    TelegramCommand,
    TelegramMessage,
    _help_response_skips_notifier_body_i18n,
)
from app.telegram.commands.branch import BranchCommand, PrCommand, PullCommand, RebaseCommand
from app.telegram.commands.clear_stop import ClearCommand, StopCommand
from app.telegram.commands.fix import FixCommand
from app.telegram.commands.model import ModelCommand
from app.telegram.commands.monitor import MonitorCommand
from app.telegram.commands.status import ReportsCommand, StatusCommand
from app.telegram.commands.system import HelpCommand, InitCommand, StartCommand
from app.telegram.i18n import translate_text


class CommandRegistry:
    def __init__(self, commands: list[TelegramCommand]) -> None:
        self._commands = {command.name: command for command in commands}
        help_cmd = self._commands.get("/help")
        if isinstance(help_cmd, HelpCommand):
            help_cmd._registry = self._commands

    def dispatch(self, message: TelegramMessage, ctx: CommandContext) -> str | None:
        tokens = message.text.strip().split()
        head = tokens[0] if tokens else ""
        scope_project = ctx.project_name

        if head == "/init":
            init_cmd = self._commands.get("/init")
            if init_cmd is not None:
                ctx.confirmation_store.pop(scope_project, message.chat_id)
                return init_cmd.execute(message, ctx)

        if head in {"/plan", "/ask", "/fix"}:
            return None

        pending = ctx.confirmation_store.get(scope_project, message.chat_id)
        if pending is not None:
            command = self._commands.get(pending.command_name)
            confirmed = ctx.confirmation_store.pop(scope_project, message.chat_id)
            if isinstance(command, ConfirmableCommand) and confirmed is not None:
                return command.confirm(message, ctx, confirmed)
            return "Could not process the pending confirmation."

        if not head.startswith("/"):
            return None
        command = self._commands.get(head)
        if not command:
            return "Unknown command. See /help."
        return command.execute(message, ctx)

    def dispatch_rich(self, message: TelegramMessage, ctx: CommandContext) -> CommandResponse | None:
        text = self.dispatch(message, ctx)
        if text is None:
            return None
        tokens = message.text.strip().split()
        head = tokens[0] if tokens else ""
        command = self._commands.get(head)
        buttons = command.get_inline_buttons(message, ctx) if command is not None else None
        skip_body = _help_response_skips_notifier_body_i18n(message.text)
        return CommandResponse(text=text, inline_buttons=buttons, skip_notifier_body_i18n=skip_body)

    def bot_commands(self, language: UiLanguage = UiLanguage.ENGLISH) -> list[dict[str, str]]:
        base = [
            {
                "command": command.name.removeprefix("/"),
                "description": translate_text(command.description, language),
            }
            for command in self._commands.values()
            if command.description
        ]
        return base + [
            {
                "command": "plan",
                "description": translate_text("plan mode message (example: /plan review login flow)", language),
            },
            {
                "command": "ask",
                "description": translate_text("ask mode message (example: /ask explain the JobManager role)", language),
            },
        ]


def build_default_commands() -> list[TelegramCommand]:
    return [
        StartCommand(),
        HelpCommand(),
        ModelCommand(),
        StatusCommand(),
        InitCommand(),
        ReportsCommand(),
        BranchCommand(),
        PullCommand(),
        RebaseCommand(),
        PrCommand(),
        MonitorCommand(),
        ClearCommand(),
        StopCommand(),
        FixCommand(),
    ]


def default_telegram_bot_commands() -> list[dict[str, str]]:
    return CommandRegistry(build_default_commands()).bot_commands()
