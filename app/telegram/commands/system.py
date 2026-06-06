from __future__ import annotations

from app.models import UiLanguage
from app.telegram.commands.base import (
    HELP_AGENT_TOPIC,
    HELP_ASK_TOPIC,
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
)
from app.telegram.i18n import (
    HELP_AGENT_TOPIC_EN,
    HELP_ASK_TOPIC_EN,
    HELP_MAIN_EN,
    HELP_PLAN_TOPIC_EN,
    language_from_settings_store,
)


class StartCommand(TelegramCommand):
    name = "/start"
    description = "메뉴와 프로젝트 상태를 확인합니다"

    _TOPIC_TEXT: dict[str, str] = {
        "manage": "실행할 명령을 선택하세요.",
        "modes": "확인할 모드 안내를 선택하세요.",
    }

    def execute(self, message: TelegramMessage, ctx: CommandContext) -> str:
        tokens = message.text.strip().split()
        if len(tokens) == 2:
            topic = tokens[1].lower()
            topic_text = self._TOPIC_TEXT.get(topic)
            if topic_text is not None:
                return topic_text
        project_name = effective_project_name_for_chat(ctx, message.chat_id)
        if not project_name:
            return "✅ Remote AI Coder가 준비되었습니다.\n\nRemote AI Coder에 오신 것을 환영합니다."
        entry = ctx.project_registry.get(project_name)
        if not entry:
            return (
                "✅ Remote AI Coder가 준비되었습니다.\n\n"
                "Remote AI Coder에 오신 것을 환영합니다.\n"
                f"- 프로젝트: {project_name} (등록 정보 없음)"
            )
        try:
            current_branch = ctx.git_service.get_current_branch(entry.root_path)
        except RuntimeError:
            current_branch = "(확인 실패)"
        state = "enabled" if entry.enabled else "disabled"
        return "\n".join(
            [
                "✅ Remote AI Coder가 준비되었습니다.",
                "",
                "Remote AI Coder에 오신 것을 환영합니다.",
                f"- 프로젝트: {entry.name}",
                f"- root_path: {entry.root_path}",
                f"- default_model: {entry.default_model.value}",
                f"- current_branch: {current_branch}",
                f"- worktree_base_dir: {entry.worktree_base_dir}",
                f"- enabled: {state}",
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
            return [
                [
                    InlineButton("브랜치 확인", "/branch"),
                    InlineButton("Pull", "/pull"),
                ],
                [
                    InlineButton("리베이스", "/rebase"),
                    InlineButton("PR 올리기", "/pr"),
                ],
                [
                    InlineButton("중단", "/stop"),
                    InlineButton("상태", "/status"),
                ],
                [
                    InlineButton("모델", "/model"),
                    InlineButton("초기화", "/init"),
                ],
                [
                    InlineButton("뒤로", "/start"),
                ],
            ]
        if topic == "modes":
            return [
                [
                    InlineButton("AGENTS 모드", "/help agent"),
                    InlineButton("PLAN 모드", "/help plan"),
                    InlineButton("ASK 모드", "/help ask"),
                ],
                [InlineButton("뒤로", "/start")],
            ]
        return [
            [InlineButton("도움말", "/help"), InlineButton("모드별 안내", "/start modes")],
            [InlineButton("모니터링", "/monitor"), InlineButton("정리", "/clear")],
            [InlineButton("관리", "/start manage"), InlineButton("리포트", "/reports")],
        ]


class HelpCommand(TelegramCommand):
    name = "/help"
    description = "사용 가능한 명령어를 확인합니다"
    _registry: dict[str, TelegramCommand] | None = None

    def execute(self, message: TelegramMessage, ctx: CommandContext) -> str:
        lang = language_from_settings_store(ctx.advanced_settings_store)
        tokens = message.text.strip().split()
        if len(tokens) >= 2:
            raw = tokens[1]
            topic_aliases = {"에이전트": "agent", "계획": "plan", "질문": "ask"}
            topic = topic_aliases.get(raw, raw.lower())
            if topic in ("agent", "agents"):
                return HELP_AGENT_TOPIC if lang == UiLanguage.KOREAN else HELP_AGENT_TOPIC_EN
            if topic == "plan":
                return HELP_PLAN_TOPIC if lang == UiLanguage.KOREAN else HELP_PLAN_TOPIC_EN
            if topic == "ask":
                return HELP_ASK_TOPIC if lang == UiLanguage.KOREAN else HELP_ASK_TOPIC_EN
        if len(tokens) >= 2 and self._registry is not None:
            subcmd = self._registry.get("/" + tokens[1])
            if subcmd is not None and subcmd.menu_text:
                return subcmd.menu_text
        return HELP_TEXT if lang == UiLanguage.KOREAN else HELP_MAIN_EN

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
            if topic in ("agent", "agents", "plan", "ask"):
                return [[InlineButton("← 뒤로", "/help")]]
            subcmd = self._registry.get("/" + tokens[1])
            if subcmd is not None:
                sub_buttons = subcmd.get_inline_buttons(None, ctx) or []
                return sub_buttons + [[InlineButton("← 뒤로", "/help")]]
        menu_cmds = [
            cmd for name, cmd in self._registry.items()
            if name not in ("/help", "/start") and cmd.menu_text
        ]
        if not menu_cmds:
            return None
        buttons = [InlineButton(cmd.name[1:], f"/help {cmd.name[1:]}") for cmd in menu_cmds]
        return _button_rows(buttons, per_row=2)


class InitCommand(TelegramCommand):
    name = "/init"
    description = "모델 설정과 확인 대기 상태를 초기화합니다"

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
                "이 채팅의 기본 모델·확인 대기 상태를 초기화했습니다.\n"
                "프로젝트 컨텍스트가 설정되지 않았습니다."
            )

        entry = ctx.project_registry.get(project_name)
        if not entry:
            return (
                "이 채팅의 기본 모델·확인 대기 상태를 초기화했습니다.\n"
                f"프로젝트 `{project_name}` 을(를) 찾을 수 없습니다. "
                "관리 화면에서 프로젝트 설정을 확인하세요."
            )
        if not entry.enabled:
            return (
                "이 채팅의 기본 모델·확인 대기 상태를 초기화했습니다.\n"
                f"프로젝트 `{project_name}` 이(가) 비활성화되어 있습니다. "
                "관리 화면에서 활성화 상태를 확인하세요."
            )

        model = effective_model_for_chat(ctx, chat_id, project_name)
        return (
            "이 채팅의 기본 모델·확인 대기 상태를 초기화했습니다.\n"
            f"적용 프로젝트: {project_name}\n"
            f"기본 모델: {model.value}"
        )
