from __future__ import annotations

from app import __version__
from app.telegram.commands.base import (
    HELP_AGENT_TOPIC,
    HELP_ASK_TOPIC,
    HELP_FIX_TOPIC,
    HELP_PLAN_TOPIC,
    HELP_TEXT,
    CommandContext,
    InlineButton,
    TelegramCommand,
    TelegramMessage,
    _button_rows,
    _cmd_evt,
    effective_model_for_chat,
    effective_project_name_for_chat,
    format_usage,
    with_nav_row,
)


class StartCommand(TelegramCommand):
    name = "/start"
    description = "Show the menu and project status"

    _TOPIC_TEXT: dict[str, str] = {
        "manage": "Choose a command.",
        "modes": "Choose a mode guide.",
    }

    @staticmethod
    def _ready_line() -> str:
        return f"✅ Remote AI Coder v{__version__} is ready."

    def execute(self, message: TelegramMessage, ctx: CommandContext) -> str:
        tokens = message.text.strip().split()
        if len(tokens) == 2:
            topic = tokens[1].lower()
            topic_text = self._TOPIC_TEXT.get(topic)
            if topic_text is not None:
                return topic_text
        project_name = effective_project_name_for_chat(ctx, message.chat_id)
        if not project_name:
            return (
                f"{self._ready_line()}\n\n"
                "Welcome to Remote AI Coder.\n"
                "Send a coding request or tap Help to start."
            )
        entry = ctx.project_registry.get(project_name)
        if not entry:
            return (
                f"{self._ready_line()}\n\n"
                f"- Project: {project_name} (not registered)"
            )
        if not entry.enabled:
            return (
                f"{self._ready_line()}\n\n"
                f"- Project: {entry.name} (disabled)"
            )
        try:
            current_branch = ctx.git_service.get_current_branch(entry.root_path)
        except RuntimeError:
            current_branch = "(check failed)"
        return "\n".join(
            [
                self._ready_line(),
                "",
                f"- Project: {entry.name}",
                f"- Model: {entry.default_model.value}",
                f"- Branch: {current_branch}",
                "",
                "Send a coding request or tap Help to start.",
            ]
        )

    def get_inline_buttons(
        self,
        message: TelegramMessage | None = None,
        ctx: CommandContext | None = None,
    ) -> list[list[InlineButton]] | None:
        tokens = message.text.strip().split() if message is not None else []
        topic = tokens[1].lower() if len(tokens) == 2 else ""

        if topic == "manage":
            return with_nav_row(
                [
                    [InlineButton("Branch", "/branch"), InlineButton("Pull", "/pull")],
                    [InlineButton("Rebase", "/rebase"), InlineButton("Open PR", "/pr")],
                    [InlineButton("Stop", "/stop"), InlineButton("Status", "/status")],
                    [InlineButton("Model", "/model"), InlineButton("Reset", "/init")],
                ],
                back_to="/start",
            )
        if topic == "modes":
            return with_nav_row(
                [
                    [
                        InlineButton("AGENTS mode", "/help agent"),
                        InlineButton("PLAN mode", "/help plan"),
                        InlineButton("ASK mode", "/help ask"),
                        InlineButton("FIX mode", "/help fix"),
                    ],
                ],
                back_to="/start",
            )
        return with_nav_row(
            [
                [InlineButton("Help", "/help"), InlineButton("Modes", "/start modes")],
                [InlineButton("Monitor", "/monitor"), InlineButton("Clean", "/clear")],
                [InlineButton("Manage", "/start manage"), InlineButton("Reports", "/reports")],
            ]
        )


class HelpCommand(TelegramCommand):
    name = "/help"
    description = "Show available commands"
    _registry: dict[str, TelegramCommand] | None = None

    def execute(self, message: TelegramMessage, ctx: CommandContext) -> str:
        tokens = message.text.strip().split()
        if len(tokens) >= 2:
            raw = tokens[1]
            topic_aliases = {"에이전트": "agent", "계획": "plan", "질문": "ask", "수정": "fix"}
            topic = topic_aliases.get(raw, raw.lower())
            if topic in ("agent", "agents"):
                return HELP_AGENT_TOPIC
            if topic == "plan":
                return HELP_PLAN_TOPIC
            if topic == "ask":
                return HELP_ASK_TOPIC
            if topic == "fix":
                return HELP_FIX_TOPIC
        if len(tokens) >= 2 and self._registry is not None:
            subcmd = self._registry.get("/" + tokens[1])
            if subcmd is not None and subcmd.menu_text:
                return subcmd.menu_text
        return HELP_TEXT

    def get_inline_buttons(
        self,
        message: TelegramMessage | None = None,
        ctx: CommandContext | None = None,
    ) -> list[list[InlineButton]] | None:
        if self._registry is None:
            return None
        tokens = message.text.strip().split() if message else []
        if len(tokens) >= 2:
            topic = tokens[1].lower()
            if topic in ("agent", "agents", "plan", "ask", "fix"):
                return with_nav_row(None, back_to="/help")
            subcmd = self._registry.get("/" + tokens[1])
            if subcmd is not None:
                sub_buttons = subcmd.get_inline_buttons(None, ctx) or []
                return with_nav_row(sub_buttons, back_to="/help")
        menu_cmds = [
            cmd for name, cmd in self._registry.items()
            if name not in ("/help", "/start") and cmd.menu_text
        ]
        if not menu_cmds:
            return None
        buttons = [InlineButton(cmd.name[1:], f"/help {cmd.name[1:]}") for cmd in menu_cmds]
        return with_nav_row(_button_rows(buttons, per_row=2))


class InitCommand(TelegramCommand):
    name = "/init"
    description = "Reset model settings and pending confirmations"

    def execute(self, message: TelegramMessage, ctx: CommandContext) -> str:
        tokens = message.text.strip().split()
        if len(tokens) != 1:
            return format_usage("/init")

        chat_id = message.chat_id
        project_name = effective_project_name_for_chat(ctx, chat_id)
        ctx.model_preferences.clear(project_name, chat_id)
        ctx.confirmation_store.pop(project_name, chat_id)
        _cmd_evt.info("init reset", chat_id=chat_id)

        project_name = effective_project_name_for_chat(ctx, chat_id)
        if not project_name:
            return (
                "This chat's default model and pending confirmation were reset.\n"
                "No project context is configured."
            )

        entry = ctx.project_registry.get(project_name)
        if not entry:
            return (
                "This chat's default model and pending confirmation were reset.\n"
                f"Project `{project_name}` was not found. "
                "Check the project settings in the admin UI."
            )
        if not entry.enabled:
            return (
                "This chat's default model and pending confirmation were reset.\n"
                f"Project `{project_name}` is disabled. "
                "Check the enabled state in the admin UI."
            )

        model = effective_model_for_chat(ctx, chat_id, project_name)
        return (
            "This chat's default model and pending confirmation were reset.\n"
            f"Project: {project_name}\n"
            f"Default model: {model.value}"
        )
