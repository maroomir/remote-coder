from __future__ import annotations

from app.jobs.mode_registry import get_mode_registry
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
from app.telegram.commands.result_actions import CherryPickCommand, DiscardCommand
from app.telegram.commands.status import LogCommand, ReportsCommand, StatusCommand
from app.telegram.commands.system import HelpCommand, InitCommand, StartCommand
from app.telegram.i18n import translate_text


# Existing setMyCommands descriptions for the builtin slash modes, kept verbatim so the bot menu
# stays byte-identical after the move to registry-driven generation. Addon modes derive their
# description from the spec help/label instead.
_BUILTIN_MODE_COMMAND_DESCRIPTIONS = {
    "plan": "plan mode message (example: /plan review login flow)",
    "ask": "ask mode message (example: /ask explain the JobManager role)",
    "research": "research mode message (example: /research compare webhook retry strategies)",
}


def _mode_slash_passthrough() -> set[str]:
    # Slash mode triggers handled by the natural-language flow rather than a TelegramCommand. /fix
    # is a real command but routes through the fix flow, so it is included explicitly.
    registry = get_mode_registry()
    passthrough = {f"/{name}" for name in registry.slash_names()}
    passthrough.add("/fix")
    return passthrough


def _mode_command_description(mode_name: str) -> str:
    builtin = _BUILTIN_MODE_COMMAND_DESCRIPTIONS.get(mode_name)
    if builtin is not None:
        return builtin
    spec = get_mode_registry().lookup(mode_name)
    if spec is not None and spec.help.get("en"):
        return spec.help["en"]
    if spec is not None and spec.label.get("en"):
        return spec.label["en"]
    return f"{mode_name} mode"


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

        if head in _mode_slash_passthrough():
            return None

        pending = ctx.confirmation_store.get(scope_project, message.chat_id)
        if pending is not None:
            # A fresh slash command for a *different* command starts over instead of being
            # swallowed as a (cancelling) confirmation. This keeps the per-branch result-card
            # actions from silently cancelling each other when the user taps one button, then
            # another, before confirming. The same command's confirm tokens are not slash
            # commands, so the normal confirm path below is unaffected.
            is_fresh_other_command = (
                head.startswith("/")
                and head in self._commands
                and head != pending.command_name
            )
            if not is_fresh_other_command:
                command = self._commands.get(pending.command_name)
                confirmed = ctx.confirmation_store.pop(scope_project, message.chat_id)
                if isinstance(command, ConfirmableCommand) and confirmed is not None:
                    return command.confirm(message, ctx, confirmed)
                return "Could not process the pending confirmation."
            ctx.confirmation_store.pop(scope_project, message.chat_id)

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
        return CommandResponse(
            text=text,
            inline_buttons=buttons,
            skip_notifier_body_i18n=skip_body,
            prefer_edit=buttons is not None,
        )

    def bot_commands(self, language: UiLanguage = UiLanguage.ENGLISH) -> list[dict[str, str]]:
        base = [
            {
                "command": command.name.removeprefix("/"),
                "description": translate_text(command.description, language),
            }
            for command in self._commands.values()
            if command.description
        ]
        mode_entries = [
            {
                "command": name,
                "description": translate_text(_mode_command_description(name), language),
            }
            for name in get_mode_registry().slash_names()
        ]
        return base + mode_entries


def build_default_commands() -> list[TelegramCommand]:
    return [
        StartCommand(),
        HelpCommand(),
        ModelCommand(),
        StatusCommand(),
        LogCommand(),
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
        DiscardCommand(),
        CherryPickCommand(),
    ]


def default_telegram_bot_commands() -> list[dict[str, str]]:
    return CommandRegistry(build_default_commands()).bot_commands()
