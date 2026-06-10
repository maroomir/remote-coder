from __future__ import annotations

from app.telegram.commands.base import TelegramCommand, TelegramMessage, CommandContext

FIX_SOURCE_AWAIT_ACTION = "fix_source_await_instruction"
FIX_SOURCE_PENDING_ACTION = "fix_source"


class FixCommand(TelegramCommand):
    name = "/fix"
    menu_text = "Fix mode amends the linked job commit (reply to a job result first)."
    description = "Fix the linked job commit (reply to a job result, then /fix or fix:)"

    def execute(self, message: TelegramMessage, ctx: CommandContext) -> str:
        _ = (message, ctx)
        return (
            "Fix mode requires replying to a job result message.\n\n"
            "Example: reply to a job result, then send /fix or fix: add missing tests"
        )
