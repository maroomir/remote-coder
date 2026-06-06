from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.jobs.schemas import Job
from app.jobs.store import JobStore
from app.models import ModelName
from app.monitoring.events import EventLogger
from app.projects.registry import ProjectRegistry
from app.telegram.confirmations import InMemoryConfirmationStore, PendingConfirmation
from app.telegram.conversation import SQLiteConversationStore
from app.telegram.model_preferences import InMemoryModelPreferenceStore, ModelPreference

if TYPE_CHECKING:
    from app.admin.advanced_settings import FileAdvancedSettingsStore
    from app.git.service import GitWorktreeService
    from app.jobs.manager import JobManager

_cmd_evt = EventLogger("app.telegram.command", "telegram.command")


@dataclass
class TelegramMessage:
    chat_id: int
    user_id: int | None
    text: str


@dataclass
class CommandContext:
    job_store: JobStore
    default_model: ModelName
    project_registry: ProjectRegistry
    model_preferences: InMemoryModelPreferenceStore
    project_name: str | None
    git_service: GitWorktreeService
    git_remote_name: str
    confirmation_store: InMemoryConfirmationStore
    conversation_store: SQLiteConversationStore | None = None
    job_manager: JobManager | None = None
    advanced_settings_store: FileAdvancedSettingsStore | None = None


def format_usage(*lines: str) -> str:
    return "사용법\n\n" + "\n".join(f"- {line}" for line in lines)


MODEL_USAGE = "<claude|codex|gemini>"


@dataclass
class InlineButton:
    label: str
    callback_data: str


@dataclass
class CommandResponse:
    text: str
    inline_buttons: list[list["InlineButton"]] | None = None
    skip_notifier_body_i18n: bool = False


def _help_response_skips_notifier_body_i18n(message_text: str) -> bool:
    tokens = message_text.strip().split()
    if not tokens or tokens[0] != "/help":
        return False
    if len(tokens) == 1:
        return True
    raw = tokens[1]
    topic_aliases = {"에이전트": "agent", "계획": "plan", "질문": "ask"}
    topic = topic_aliases.get(raw, raw.lower())
    return topic in ("agent", "agents", "plan", "ask")


HELP_TEXT = "\n".join(
    [
        "도움말",
        "",
        "작업 지시는 일반 메시지로 보내세요.",
        "",
        "옵션",
        "- model:",
        "- branch:",
        "- no commit",
        "- plan: <자연어> 또는 /plan <자연어> - 계획 모드 (코드 수정 없이 변경 계획만 응답)",
        "- ask: <자연어> 또는 /ask <자연어> - 질문 모드 (코드 분석 후 응답)",
        "- 계획: 또는 질문: (한글 접두, 콜론 `:` 또는 `：` 가능)",
        "",
        "명령어 목록:",
        "- /model <claude|codex|gemini>: 기본 모델 변경",
        "- /status <job_id>: 작업 상태 확인",
        "- /branch [이름]: 브랜치 조회 또는 전환",
        "- /pull: 원격 저장소의 모든 브랜치 pull",
        "- /rebase [브랜치]: 브랜치 리베이스",
        "- /pr [브랜치]: 브랜치를 GitHub PR로 올리기",
        "- /monitor <model|memory|branch|worktrees|code|project>: 모니터링",
        "- /clear <branch|worktrees|memory>: 정리 (확인 필요)",
        "- /reports [개수]: 대화 기억 리포트",
        "- /init: 이 채팅 설정 초기화",
        "- /stop <job_id>: 진행 중인 작업 중단",
        "- /fix <commit|source> [job_id]: 기존 Job의 커밋/소스 재작업 (amend + force-with-lease push)",
        "- /start: 인라인 메뉴",
    ]
)

HELP_AGENT_TOPIC = "\n".join(
    [
        "AGENTS 모드 (agent)",
        "",
        "일반 자연어 작업 요청입니다. 현재 프로젝트에서 코드를 수정할 수 있으며, 변경 사항이 있으면 브랜치·커밋·push까지 진행할 수 있습니다.",
        "",
        "입력 예",
        "- 로그인 검증 버그 수정해줘",
        "- model: codex branch: remote-auth 테스트 보강해줘",
        "- no commit 문서 문구만 확인해줘",
        "",
        "작업은 프로젝트·브랜치·모델을 확인한 뒤 `y`/`Y` 또는 인라인 버튼으로 접수됩니다.",
    ]
)

HELP_PLAN_TOPIC = "\n".join(
    [
        "계획 모드 (plan)",
        "",
        "코드를 수정하지 않고 변경 계획만 받습니다. 일반 자연어(agent)와 같이 확인(`y`/`Y` 또는 인라인 버튼) 후 Job이 접수됩니다.",
        "",
        "입력 예",
        "- plan: 로그인 검증 흐름 정리해줘",
        "- /plan model: codex API 경계 리스크만 나열해줘",
        "- 계획：리팩터링 단계 (전각 콜론)",
        "",
        "자세한 옵션은 /help 를 참고하세요.",
    ]
)

HELP_ASK_TOPIC = "\n".join(
    [
        "질문 모드 (ask)",
        "",
        "저장소를 읽고 질문에 답합니다. 코드 수정·커밋·push는 하지 않으며, Job 접수는 agent와 같이 확인(`y`/`Y` 또는 인라인 버튼) 후입니다.",
        "",
        "입력 예",
        "- ask: 이 프로젝트에서 pytest 어떻게 돌려?",
        "- /ask JobManager.run 단계 설명해줘",
        "- 질문：에러 로그 이 줄 의미",
        "",
        "자세한 옵션은 /help 를 참고하세요.",
    ]
)


def _button_rows(buttons: list[InlineButton], per_row: int = 2) -> list[list[InlineButton]]:
    return [buttons[i : i + per_row] for i in range(0, len(buttons), per_row)]


def _job_button_label(job: Job) -> str:
    return f"{job.id} ({job.status.value})"


def _confirmation_buttons_enabled(ctx: CommandContext) -> bool:
    if ctx.advanced_settings_store is None:
        return False
    return ctx.advanced_settings_store.get().natural_job_confirmation_buttons_enabled


def effective_project_name_for_chat(ctx: CommandContext, chat_id: int) -> str | None:
    _ = chat_id
    return ctx.project_name


def effective_model_for_chat(ctx: CommandContext, chat_id: int, project_name: str | None) -> ModelName:
    explicit = ctx.model_preferences.get_explicit(project_name, chat_id)
    if explicit is not None:
        return explicit
    if project_name:
        entry = ctx.project_registry.get(project_name)
        if entry is not None:
            return entry.default_model
    return ctx.default_model


def effective_model_selection_for_chat(
    ctx: CommandContext,
    chat_id: int,
    project_name: str | None,
) -> ModelPreference:
    explicit = ctx.model_preferences.get_explicit_selection(project_name, chat_id)
    if explicit is not None:
        return explicit
    if project_name:
        entry = ctx.project_registry.get(project_name)
        if entry is not None:
            return ModelPreference(entry.default_model)
    return ModelPreference(ctx.default_model)


class TelegramCommand(ABC):
    name: str
    menu_text: str | None = None
    description: str | None = None

    @abstractmethod
    def execute(self, message: TelegramMessage, ctx: CommandContext) -> str:
        raise NotImplementedError

    def get_inline_buttons(
        self,
        message: TelegramMessage | None = None,
        ctx: CommandContext | None = None,
    ) -> list[list[InlineButton]] | None:
        _ = (message, ctx)
        return None


class ConfirmableCommand(TelegramCommand):
    @abstractmethod
    def confirm(
        self,
        message: TelegramMessage,
        ctx: CommandContext,
        pending: PendingConfirmation,
    ) -> str:
        raise NotImplementedError
