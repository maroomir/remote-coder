from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.ai.usage import format_token_usage
from app.jobs.schemas import Job, JobStatus
from app.jobs.store import InMemoryJobStore
from app.models import ModelName
from app.monitoring.code import count_project_code, format_code_monitor
from app.monitoring.events import EventLogger
from app.monitoring.git import format_branch_monitor, format_worktree_monitor
from app.monitoring.memory import format_memory_monitor
from app.monitoring.model import format_model_monitor
from app.projects.registry import ProjectRecord, ProjectRegistry
from app.telegram.confirmations import InMemoryConfirmationStore, PendingConfirmation
from app.telegram.conversation import SQLiteConversationStore
from app.telegram.model_preferences import InMemoryModelPreferenceStore

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
    job_store: InMemoryJobStore
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
        "- /start: 인라인 메뉴",
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


class StartCommand(TelegramCommand):
    name = "/start"
    description = "메뉴와 프로젝트 상태를 확인합니다"

    _TOPIC_TEXT: dict[str, str] = {
        "model": "모델을 선택하세요.",
        "monitor": "확인할 모니터링 항목을 선택하세요.",
        "clear": "정리할 항목을 선택하세요. 실행 전 y/Y 확인이 필요합니다.",
        "manage": "실행할 명령을 선택하세요.",
    }

    def execute(self, message: TelegramMessage, ctx: CommandContext) -> str:
        tokens = message.text.strip().split()
        if len(tokens) == 2:
            topic = tokens[1].lower()
            if topic == "clear" and _confirmation_buttons_enabled(ctx):
                return "정리할 항목을 선택하세요.\n\n- 실행 전 확인이 필요합니다."
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

        if topic == "model":
            return [
                [
                    InlineButton("claude", "/model claude"),
                    InlineButton("codex", "/model codex"),
                    InlineButton("gemini", "/model gemini"),
                ],
                [InlineButton("뒤로", "/start")],
            ]
        if topic == "monitor":
            return [
                [
                    InlineButton("model", "/monitor model"),
                    InlineButton("memory", "/monitor memory"),
                    InlineButton("branch", "/monitor branch"),
                ],
                [
                    InlineButton("worktrees", "/monitor worktrees"),
                    InlineButton("code", "/monitor code"),
                    InlineButton("project", "/monitor project"),
                ],
                [InlineButton("뒤로", "/start")],
            ]
        if topic == "clear":
            return [
                [
                    InlineButton("branch", "/clear branch"),
                    InlineButton("worktrees", "/clear worktrees"),
                    InlineButton("memory", "/clear memory"),
                ],
                [InlineButton("뒤로", "/start")],
            ]
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
                    InlineButton("초기화", "/init"),
                    InlineButton("뒤로", "/start"),
                ],
            ]
        return [
            [InlineButton("계획 모드 안내", "/help plan"), InlineButton("질문 모드 안내", "/help ask")],
            [InlineButton("모델", "/start model")],
            [InlineButton("모니터링", "/start monitor"), InlineButton("정리", "/start clear")],
            [InlineButton("관리", "/start manage"), InlineButton("리포트", "/reports")],
        ]


class HelpCommand(TelegramCommand):
    name = "/help"
    description = "사용 가능한 명령어를 확인합니다"
    _registry: dict[str, TelegramCommand] | None = None

    def execute(self, message: TelegramMessage, ctx: CommandContext) -> str:
        _ = ctx
        tokens = message.text.strip().split()
        if len(tokens) >= 2:
            raw = tokens[1]
            topic_aliases = {"계획": "plan", "질문": "ask"}
            topic = topic_aliases.get(raw, raw.lower())
            if topic == "plan":
                return HELP_PLAN_TOPIC
            if topic == "ask":
                return HELP_ASK_TOPIC
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
            if topic in ("plan", "ask"):
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


class ModelCommand(TelegramCommand):
    name = "/model"
    menu_text = "모델을 선택하세요."
    description = "채팅의 기본 AI 모델을 확인하거나 변경합니다"

    def execute(self, message: TelegramMessage, ctx: CommandContext) -> str:
        tokens = message.text.strip().split()
        project_name = effective_project_name_for_chat(ctx, message.chat_id)
        current = effective_model_for_chat(ctx, message.chat_id, project_name)
        if len(tokens) == 1:
            return f"모델 설정\n\n- 현재 기본 모델: {current.value}"
        if len(tokens) == 2 and tokens[1] in {model.value for model in ModelName}:
            selected = ModelName(tokens[1])
            ctx.model_preferences.set(project_name, message.chat_id, selected)
            return f"모델 설정이 변경되었습니다.\n\n- 기본 모델을 {selected.value}로 변경했습니다."
        return format_usage("/model", f"/model {MODEL_USAGE}")

    def get_inline_buttons(
        self,
        message: TelegramMessage | None = None,
        ctx: CommandContext | None = None,
    ) -> list[list[InlineButton]] | None:
        _ = ctx
        return [
            [
                InlineButton("claude", "/model claude"),
                InlineButton("codex", "/model codex"),
                InlineButton("gemini", "/model gemini"),
            ]
        ]


_STATUS_EMOJI: dict[str, str] = {
    "queued": "⏳",
    "running": "🔄",
    "succeeded": "✅",
    "failed": "❌",
    "cancelled": "⛔",
}
_STDOUT_TAIL = 1500
_STDERR_TAIL = 800
_MAX_CHANGED_FILES = 10


class StatusCommand(TelegramCommand):
    name = "/status"
    description = "최근 Job 목록과 작업 상태를 조회합니다"

    def execute(self, message: TelegramMessage, ctx: CommandContext) -> str:
        tokens = message.text.strip().split()
        project_name = effective_project_name_for_chat(ctx, message.chat_id)
        if len(tokens) == 1:
            if not project_name:
                return (
                    "등록된 프로젝트가 없습니다. "
                    "브라우저에서 http://127.0.0.1:8000/projects 로 프로젝트를 등록하세요."
                )
            limit = self._job_limit(ctx)
            jobs = ctx.job_store.list_recent_for_project_chat(
                project_name, message.chat_id, limit
            )
            if not jobs:
                return "조회할 수 있는 Job이 없습니다."
            return "조회할 Job을 선택하세요."
        if len(tokens) != 2:
            return format_usage("/status <job_id>")
        job = ctx.job_store.get(tokens[1])
        if not job:
            return "해당 Job ID를 찾을 수 없습니다."
        if project_name and job.request.project != project_name:
            return "해당 Job ID를 찾을 수 없습니다."
        return self._format_job_detail(job)

    @staticmethod
    def _fmt_time(dt: datetime) -> str:
        return dt.astimezone().strftime("%H:%M:%S")

    @staticmethod
    def _duration_str(seconds: int) -> str:
        mins, secs = divmod(seconds, 60)
        return f"{mins}분 {secs}초" if mins > 0 else f"{secs}초"

    @classmethod
    def _format_job_detail(cls, job: Job) -> str:
        lines: list[str] = []
        emoji = _STATUS_EMOJI.get(job.status.value, "")
        lines.append(f"Job {job.id}")
        lines.append("")
        lines.append(f"- 상태: {job.status.value} {emoji}")
        lines.append(f"- 프로젝트: {job.request.project}")
        lines.append(f"- 요청 모델: {job.request.model.value}")
        lines.append(f"- 사용 모델: {job.runner_actual_model or job.request.model.value}")
        lines.append(f"- 토큰 사용량: {format_token_usage(job.runner_token_usage) or '확인 불가'}")

        instr = job.request.instruction.strip().replace("\n", " ")
        if len(instr) > 80:
            instr = instr[:80].rstrip() + "..."
        lines.append(f"- 지시: {instr}")

        now = datetime.now(UTC)
        started = job.started_at
        finished = job.finished_at
        if started:
            if finished:
                elapsed = int((finished - started).total_seconds())
                lines.append(
                    f"- 시작: {cls._fmt_time(started)} → 완료: {cls._fmt_time(finished)}"
                    f" (소요: {cls._duration_str(elapsed)})"
                )
            else:
                elapsed = int((now - started).total_seconds())
                lines.append(
                    f"- 시작: {cls._fmt_time(started)} (경과: {cls._duration_str(elapsed)})"
                )
        else:
            lines.append(f"- 생성: {cls._fmt_time(job.created_at)}")

        if job.status.value == "succeeded":
            if job.branch:
                lines.append(f"- 브랜치: {job.branch}")
            if job.commit_hash:
                lines.append(f"- 커밋: {job.commit_hash[:8]}")
            if job.changed_files:
                lines.append("")
                lines.append(f"변경 파일 ({len(job.changed_files)}개)")
                for f in job.changed_files[:_MAX_CHANGED_FILES]:
                    lines.append(f"- {f}")
                if len(job.changed_files) > _MAX_CHANGED_FILES:
                    lines.append(f"- ... 외 {len(job.changed_files) - _MAX_CHANGED_FILES}개")
            else:
                lines.append("- 변경 파일: 없음 (no-op)")
            if job.runner_stdout_summary:
                lines.append("")
                lines.append("[AI 출력 요약]")
                summary = job.runner_stdout_summary
                if len(summary) > _STDOUT_TAIL:
                    summary = "...(앞부분 생략)\n" + summary[-_STDOUT_TAIL:]
                lines.append(summary)

        elif job.status.value == "failed":
            if job.error_stage:
                lines.append(f"- 오류 단계: {job.error_stage}")
            if job.error:
                lines.append(f"- 오류: {job.error[:300]}")
            if job.runner_stderr_summary:
                lines.append("")
                lines.append("[stderr]")
                lines.append(job.runner_stderr_summary[-_STDERR_TAIL:])

        elif job.status.value == "running" and job.runner_stdout_summary:
            lines.append("")
            lines.append("[현재 출력]")
            lines.append(job.runner_stdout_summary[-_STDOUT_TAIL:])

        return "\n".join(lines)

    @staticmethod
    def _job_limit(ctx: CommandContext) -> int:
        if ctx.advanced_settings_store is None:
            return 10
        return ctx.advanced_settings_store.get().status_recent_job_limit

    def get_inline_buttons(
        self,
        message: TelegramMessage | None = None,
        ctx: CommandContext | None = None,
    ) -> list[list[InlineButton]] | None:
        if message is None or ctx is None:
            return None
        if len(message.text.strip().split()) != 1:
            return None
        project_name = effective_project_name_for_chat(ctx, message.chat_id)
        if not project_name:
            return None
        limit = self._job_limit(ctx)
        jobs = ctx.job_store.list_recent_for_project_chat(
            project_name, message.chat_id, limit
        )
        if not jobs:
            return None
        return _button_rows(
            [InlineButton(_job_button_label(job), f"/status {job.id}") for job in jobs],
            per_row=1,
        )


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


class ReportsCommand(TelegramCommand):
    name = "/reports"
    description = "현재 채팅의 대화 기억 요약을 조회합니다"

    _DEFAULT_RECENT_LIMIT = 5
    _MAX_RECENT_LIMIT = 10

    def execute(self, message: TelegramMessage, ctx: CommandContext) -> str:
        tokens = message.text.strip().split()
        if len(tokens) > 2:
            return "사용법: /reports 또는 /reports <recent_limit>"

        recent_limit = self._DEFAULT_RECENT_LIMIT
        if len(tokens) == 2:
            try:
                recent_limit = int(tokens[1])
            except ValueError:
                return "사용법: /reports 또는 /reports <recent_limit>"
            if recent_limit < 1 or recent_limit > self._MAX_RECENT_LIMIT:
                return f"recent_limit 은 1~{self._MAX_RECENT_LIMIT} 사이의 숫자여야 합니다."

        if ctx.conversation_store is None:
            return "대화 기억 저장소가 설정되지 않았습니다."

        project_name = effective_project_name_for_chat(ctx, message.chat_id)
        if not project_name:
            return (
                "등록된 프로젝트가 없습니다. "
                "브라우저에서 http://127.0.0.1:8000/projects 로 프로젝트를 등록하세요."
            )

        entry = ctx.project_registry.get(project_name)
        if not entry:
            return f"알 수 없는 프로젝트: {project_name}"
        if not entry.enabled:
            return f"비활성화된 프로젝트: {project_name}"

        report = ctx.conversation_store.generate_report(project_name, message.chat_id, recent_limit)
        if report is None:
            return f"기억된 대화 기록이 없습니다. (project={project_name})"

        lines = [
            "기억 리포트",
            f"프로젝트: {project_name}",
            f"총 기록: {report.total_entries}개",
            f"사용자 요청: {report.count_for('user')}개",
            f"Job 접수: {report.count_for('job_accepted')}개",
            f"Job 결과: {report.count_for('job_result')}개",
        ]
        if report.latest_user_text:
            lines.append(f"최근 사용자 요청: {self._truncate(report.latest_user_text)}")
        if report.latest_job_result:
            job_label = report.latest_job_id or "(job_id 없음)"
            lines.append(f"최근 Job 결과: {job_label} {self._truncate(report.latest_job_result)}")
        if report.recent_entries:
            lines.append("")
            lines.append("최근 기억")
            for item in report.recent_entries:
                label = item.role
                if item.job_id:
                    label = f"{label}:{item.job_id}"
                lines.append(f"- [{label}] {self._truncate(item.text, limit=90)}")
        return "\n".join(lines)

    @staticmethod
    def _truncate(text: str, limit: int = 120) -> str:
        normalized = text.strip().replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
        if len(normalized) <= limit:
            return normalized
        return normalized[:limit].rstrip() + "..."


class BranchCommand(TelegramCommand):
    name = "/branch"
    description = "현재 브랜치를 확인하거나 로컬 브랜치로 전환합니다"

    def execute(self, message: TelegramMessage, ctx: CommandContext) -> str:
        tokens = message.text.strip().split()
        if len(tokens) > 2:
            return format_usage("/branch", "/branch <브랜치이름>")

        project_name = effective_project_name_for_chat(ctx, message.chat_id)
        if not project_name:
            return "등록된 프로젝트가 없습니다. /projects 로 등록하세요."
        entry = ctx.project_registry.get(project_name)
        if not entry or not entry.enabled:
            return f"프로젝트를 찾을 수 없거나 비활성화되어 있습니다: {project_name}"

        root = entry.root_path

        if len(tokens) == 1:
            try:
                current = ctx.git_service.get_current_branch(root)
            except RuntimeError as exc:
                return f"/branch 실패: {exc}"
            return f"프로젝트: {project_name}\n현재 브랜치: {current}"

        branch = tokens[1]
        from app.git.service import GitWorktreeService

        err = GitWorktreeService.validate_branch_token(branch)
        if err:
            return err

        if not ctx.git_service.local_branch_exists(root, branch):
            return f"브랜치가 없습니다: `{branch}` (로컬에만 전환 가능합니다)"

        try:
            ctx.git_service.switch_branch(root, branch)
        except RuntimeError as exc:
            return f"/branch 실패: {exc}"
        return f"프로젝트: {project_name}\n`{branch}` 로 전환했습니다 (git switch)."

    def get_inline_buttons(
        self,
        message: TelegramMessage | None = None,
        ctx: CommandContext | None = None,
    ) -> list[list[InlineButton]] | None:
        if message is None or ctx is None:
            return None
        if len(message.text.strip().split()) != 1:
            return None
        project_name = effective_project_name_for_chat(ctx, message.chat_id)
        if not project_name:
            return None
        entry = ctx.project_registry.get(project_name)
        if not entry or not entry.enabled:
            return None
        try:
            branches = ctx.git_service.list_local_branches(entry.root_path)
        except RuntimeError:
            return None
        if not isinstance(branches, list):
            return None
        buttons = [InlineButton(branch, f"/branch {branch}") for branch in branches]
        return _button_rows(buttons, per_row=1) if buttons else None


class RebaseCommand(TelegramCommand):
    name = "/rebase"
    description = "브랜치를 main 기준으로 rebase하고 push합니다"

    def execute(self, message: TelegramMessage, ctx: CommandContext) -> str:
        tokens = message.text.strip().split()
        if len(tokens) > 2:
            return format_usage("/rebase", "/rebase <branch>")
        if len(tokens) == 2:
            branch = tokens[1]
            from app.git.service import GitWorktreeService

            err = GitWorktreeService.validate_branch_token(branch)
            if err:
                return err
        else:
            branches = self._list_rebase_candidates(message, ctx)
            if not branches:
                return "리베이스할 브랜치가 없습니다. /rebase <branch> 로 직접 지정할 수 있습니다."
            return "리베이스할 브랜치를 선택하세요."

        project_name = effective_project_name_for_chat(ctx, message.chat_id)
        if not project_name:
            return "등록된 프로젝트가 없습니다. /projects 로 등록하세요."
        entry = ctx.project_registry.get(project_name)
        if not entry or not entry.enabled:
            return f"프로젝트를 찾을 수 없거나 비활성화되어 있습니다: {project_name}"

        if not self._remote_branch_exists(entry.root_path, branch, ctx):
            return (
                f"`{branch}` 원격 브랜치를 `{ctx.git_remote_name}`에서 찾을 수 없습니다. "
                "이미 rebase/병합 후 삭제되었거나 아직 push되지 않은 브랜치일 수 있습니다."
            )

        ops_base = entry.worktree_base_dir / "_rebase_ops"
        try:
            summary = ctx.git_service.rebase_branch_onto_main_and_merge(
                entry.root_path,
                branch,
                ctx.git_remote_name,
                ops_base,
            )
            if self._delete_rebased_branch_enabled(ctx):
                ctx.git_service.delete_remote_branches(entry.root_path, ctx.git_remote_name, [branch])
                ctx.git_service.delete_local_branches(entry.root_path, [branch])
                summary += f"\n브랜치 `{branch}`를 로컬과 `{ctx.git_remote_name}`에서 삭제했습니다."
            return summary
        except RuntimeError as exc:
            return f"/rebase 실패: {exc}"

    def _delete_rebased_branch_enabled(self, ctx: CommandContext) -> bool:
        if ctx.advanced_settings_store is None:
            return True
        return ctx.advanced_settings_store.get().delete_rebased_branch_enabled

    def get_inline_buttons(
        self,
        message: TelegramMessage | None = None,
        ctx: CommandContext | None = None,
    ) -> list[list[InlineButton]] | None:
        if message is None or ctx is None:
            return None
        if len(message.text.strip().split()) != 1:
            return None
        branches = self._list_rebase_candidates(message, ctx)
        buttons = [InlineButton(branch, f"/rebase {branch}") for branch in branches]
        return _button_rows(buttons, per_row=1) if buttons else None

    def _list_rebase_candidates(self, message: TelegramMessage, ctx: CommandContext) -> list[str]:
        project_name = effective_project_name_for_chat(ctx, message.chat_id)
        if not project_name:
            return []
        entry = ctx.project_registry.get(project_name)
        if not entry or not entry.enabled:
            return []
        try:
            main_branch = ctx.git_service.resolve_integrate_branch(entry.root_path)
            branches = ctx.git_service.list_local_branches(entry.root_path)
        except RuntimeError:
            return []
        if not isinstance(branches, list):
            return []
        try:
            remote_branch_list = ctx.git_service.list_remote_branches_matching(entry.root_path, ctx.git_remote_name, "")
        except RuntimeError:
            return []
        if not isinstance(remote_branch_list, list):
            return []
        remote_branches = set(remote_branch_list)
        excluded = {main_branch, "main", "master"}
        return [branch for branch in branches if branch not in excluded and branch in remote_branches]

    def _remote_branch_exists(self, root_path, branch: str, ctx: CommandContext) -> bool:
        try:
            remote_branches = ctx.git_service.list_remote_branches_matching(root_path, ctx.git_remote_name, "")
        except RuntimeError:
            return False
        if not isinstance(remote_branches, list):
            return False
        return branch in remote_branches


def _branch_to_pr_title(branch: str) -> str:
    slug = branch
    if slug.startswith("remote-"):
        slug = slug[len("remote-"):]
    slug = re.sub(r"-\d{8}-\d{6}$", "", slug)
    return slug.replace("-", " ").strip() or branch


class PullCommand(TelegramCommand):
    name = "/pull"
    menu_text = "원격 저장소의 모든 브랜치 pull"
    description = "원격 브랜치 정보를 가져오고 현재 브랜치를 pull합니다"

    def execute(self, message: TelegramMessage, ctx: CommandContext) -> str:
        project_name = effective_project_name_for_chat(ctx, message.chat_id)
        if not project_name:
            return "등록된 프로젝트가 없습니다. /projects 로 등록하세요."

        entry = ctx.project_registry.get(project_name)
        if not entry or not entry.enabled:
            return f"프로젝트를 찾을 수 없거나 비활성화되어 있습니다: {project_name}"

        try:
            summary = ctx.git_service.pull_repository(entry.root_path, ctx.git_remote_name)
            _cmd_evt.info("pull success project=%s", project_name, chat_id=message.chat_id)
            return f"✅ {project_name}: {summary}"
        except RuntimeError as exc:
            _cmd_evt.error("pull failed project=%s err=%s", project_name, str(exc), chat_id=message.chat_id)
            return f"❌ {project_name} pull 실패: {exc}"


class PrCommand(TelegramCommand):
    """적용 프로젝트 저장소의 브랜치를 GitHub Pull Request로 올립니다."""

    name = "/pr"
    menu_text = "PR을 올릴 브랜치를 선택하세요."
    description = "선택한 브랜치로 GitHub Pull Request를 만듭니다"

    def execute(self, message: TelegramMessage, ctx: CommandContext) -> str:
        tokens = message.text.strip().split()
        if len(tokens) > 2:
            return format_usage("/pr", "/pr <branch>")
        if len(tokens) == 2:
            branch = tokens[1]
        else:
            branches = self._list_pr_candidates(message, ctx)
            if not branches:
                return "PR을 올릴 브랜치가 없습니다. /pr <branch> 로 직접 지정할 수 있습니다."
            return "PR을 올릴 브랜치를 선택하세요."

        project_name = effective_project_name_for_chat(ctx, message.chat_id)
        if not project_name:
            return "등록된 프로젝트가 없습니다. /projects 로 등록하세요."
        entry = ctx.project_registry.get(project_name)
        if not entry or not entry.enabled:
            return f"프로젝트를 찾을 수 없거나 비활성화되어 있습니다: {project_name}"

        try:
            base_branch = ctx.git_service.resolve_integrate_branch(entry.root_path)
        except RuntimeError as exc:
            return f"/pr 실패: {exc}"

        title, body = self._build_pr_content(branch, project_name, message.chat_id, ctx)

        try:
            pr_url = ctx.git_service.create_github_pr(
                entry.root_path,
                branch,
                base_branch,
                title,
                body,
            )
        except RuntimeError as exc:
            return f"/pr 실패: {exc}"

        return f"PR이 생성되었습니다:\n{pr_url}"

    def get_inline_buttons(
        self,
        message: TelegramMessage | None = None,
        ctx: CommandContext | None = None,
    ) -> list[list[InlineButton]] | None:
        if message is None or ctx is None:
            return None
        if len(message.text.strip().split()) != 1:
            return None
        branches = self._list_pr_candidates(message, ctx)
        buttons = [InlineButton(branch, f"/pr {branch}") for branch in branches]
        return _button_rows(buttons, per_row=1) if buttons else None

    def _list_pr_candidates(self, message: TelegramMessage, ctx: CommandContext) -> list[str]:
        project_name = effective_project_name_for_chat(ctx, message.chat_id)
        if not project_name:
            return []
        entry = ctx.project_registry.get(project_name)
        if not entry or not entry.enabled:
            return []
        try:
            main_branch = ctx.git_service.resolve_integrate_branch(entry.root_path)
            branches = ctx.git_service.list_local_branches(entry.root_path)
        except RuntimeError:
            return []
        if not isinstance(branches, list):
            return []
        excluded = {main_branch, "main", "master"}
        return [branch for branch in branches if branch not in excluded]

    def _build_pr_content(
        self,
        branch: str,
        project_name: str,
        chat_id: int,
        ctx: CommandContext,
    ) -> tuple[str, str]:
        if ctx.conversation_store is None:
            return _branch_to_pr_title(branch), f"작업 브랜치: `{branch}`"

        entries = ctx.conversation_store.get_entries_for_branch(project_name, chat_id, branch)
        if not entries:
            return _branch_to_pr_title(branch), f"작업 브랜치: `{branch}`"

        title = entries[0][0][:70].rstrip()

        body_parts: list[str] = ["## 작업 요청\n"]
        for i, (user_text, job_result) in enumerate(entries, 1):
            if len(entries) > 1:
                body_parts.append(f"### 요청 {i}\n")
            body_parts.append(f"**요청:** {user_text}\n")
            if job_result:
                body_parts.append(f"\n**AI 결과:**\n{job_result}\n")
            if i < len(entries):
                body_parts.append("\n---\n")

        return title, "\n".join(body_parts)


class MonitorCommand(TelegramCommand):
    name = "/monitor"
    description = "모델, 메모리, 브랜치, worktree 상태를 점검합니다"

    def execute(self, message: TelegramMessage, ctx: CommandContext) -> str:
        tokens = message.text.strip().split()
        if len(tokens) < 2:
            _cmd_evt.info("monitor usage requested", chat_id=message.chat_id, user_id=message.user_id)
            return format_usage(
                "/monitor <model|memory|branch|worktrees|code|project>",
                "예: /monitor model",
            )

        sub = tokens[1].lower()
        valid = {"model", "memory", "branch", "worktrees", "code", "project"}
        if sub not in valid:
            _cmd_evt.warning(
                "monitor invalid subcommand sub=%s",
                sub,
                chat_id=message.chat_id,
                user_id=message.user_id,
            )
            return format_usage(
                "/monitor <model|memory|branch|worktrees|code|project>",
                "예: /monitor memory",
            )

        if sub == "project":
            effective = effective_project_name_for_chat(ctx, message.chat_id)
            if not effective:
                return "이 봇의 프로젝트 컨텍스트를 찾을 수 없습니다."
            entry = ctx.project_registry.get(effective)
            if entry is None:
                return f"알 수 없는 프로젝트: {effective}"
            _cmd_evt.info(
                "monitor project requested effective=%s",
                effective or "-",
                chat_id=message.chat_id,
                user_id=message.user_id,
                project=effective,
            )
            state = "on" if entry.enabled else "off"
            return "\n".join(
                [
                    f"이 봇 프로젝트: {entry.name}",
                    f"상태: {state}",
                    f"root_path: {entry.root_path}",
                    f"default_model: {entry.default_model.value}",
                    f"worktree_base_dir: {entry.worktree_base_dir}",
                ]
            )

        project_name = effective_project_name_for_chat(ctx, message.chat_id)
        if not project_name:
            _cmd_evt.warning(
                "monitor requested with no project sub=%s",
                sub,
                chat_id=message.chat_id,
                user_id=message.user_id,
            )
            return (
                "등록된 프로젝트가 없습니다. "
                "브라우저에서 http://127.0.0.1:8000/projects 로 프로젝트를 등록하세요."
            )

        entry = ctx.project_registry.get(project_name)
        if not entry:
            _cmd_evt.warning(
                "monitor unknown project sub=%s",
                sub,
                chat_id=message.chat_id,
                user_id=message.user_id,
                project=project_name,
            )
            return f"알 수 없는 프로젝트: {project_name}"
        if not entry.enabled:
            _cmd_evt.warning(
                "monitor disabled project sub=%s",
                sub,
                chat_id=message.chat_id,
                user_id=message.user_id,
                project=project_name,
            )
            return f"비활성화된 프로젝트: {project_name}"

        _cmd_evt.info(
            "monitor requested sub=%s",
            sub,
            chat_id=message.chat_id,
            user_id=message.user_id,
            project=project_name,
        )
        if sub == "model":
            current = effective_model_for_chat(ctx, message.chat_id, project_name)
            body = format_model_monitor(
                current,
                recent_jobs=ctx.job_store.list_recent_for_project_chat(
                    project_name, message.chat_id, 50
                ),
                chat_id=message.chat_id,
                project=project_name,
            )
            return f"현재 채팅 기본 모델: {current.value}\n\n{body}"

        if sub == "memory":
            if ctx.conversation_store is None:
                return "대화 기억 저장소가 설정되지 않았습니다."
            stats = ctx.conversation_store.get_chat_stats(project_name, message.chat_id)
            return format_memory_monitor(stats, project_name, message.chat_id)

        if sub == "branch":
            return format_branch_monitor(
                ctx.git_service,
                entry.root_path,
                ctx.git_remote_name,
                project_name,
            )

        if sub == "worktrees":
            return format_worktree_monitor(
                ctx.git_service,
                entry.root_path,
                entry.worktree_base_dir,
                project_name,
            )

        stats = count_project_code(
            entry.root_path,
            worktree_base_dir=entry.worktree_base_dir,
        )
        _cmd_evt.info(
            "monitor code counted files=%d lines=%d skipped=%d",
            stats.files_scanned,
            stats.total_lines,
            stats.skipped_binary_or_error,
            chat_id=message.chat_id,
            user_id=message.user_id,
            project=project_name,
        )
        return format_code_monitor(stats, project_name, entry.root_path)


class ClearCommand(ConfirmableCommand):
    name = "/clear"
    description = "브랜치, worktree, 대화 기억을 확인 후 정리합니다"

    def execute(self, message: TelegramMessage, ctx: CommandContext) -> str:
        tokens = message.text.strip().split()
        if len(tokens) != 2 or tokens[1] not in {"branch", "memory", "worktrees"}:
            return "사용법: /clear branch 또는 /clear worktrees 또는 /clear memory"

        action = tokens[1]
        if action == "memory" and ctx.conversation_store is None:
            return "기억 저장소가 설정되지 않았습니다."

        ctx.confirmation_store.set(
            effective_project_name_for_chat(ctx, message.chat_id),
            message.chat_id,
            PendingConfirmation(command_name=self.name, action=action),
        )

        if action == "branch":
            summary = "이 봇 프로젝트에서 remote-* 브랜치와 연결된 worktree를 삭제합니다."
        elif action == "worktrees":
            summary = "이 봇 프로젝트의 관리 대상 worktree를 정리하고 stale 엔트리를 prune 합니다."
        else:
            summary = "이 봇 프로젝트에서 이 채팅방의 대화 기억만 삭제합니다."
        if _confirmation_buttons_enabled(ctx):
            return f"현재 할 작업: {summary}\n실행 여부를 선택하세요."
        return (
            f"현재 할 작업: {summary}\n"
            "실행하려면 `y` 또는 `Y`를 입력하세요. 그 외 응답은 취소됩니다."
        )

    def get_inline_buttons(
        self,
        message: TelegramMessage | None = None,
        ctx: CommandContext | None = None,
    ) -> list[list[InlineButton]] | None:
        if message is None or ctx is None or not _confirmation_buttons_enabled(ctx):
            return None
        pending = ctx.confirmation_store.get(
            effective_project_name_for_chat(ctx, message.chat_id),
            message.chat_id,
        )
        if pending is None or pending.command_name != self.name:
            return None
        return [[InlineButton("네", "Y"), InlineButton("아니오", "n")]]

    def confirm(
        self,
        message: TelegramMessage,
        ctx: CommandContext,
        pending: PendingConfirmation,
    ) -> str:
        if message.text.strip() not in {"y", "Y"}:
            if pending.action == "branch":
                target = "브랜치 삭제"
            elif pending.action == "worktrees":
                target = "worktree 정리"
            else:
                target = "기억 삭제"
            return f"{target}를 취소했습니다."

        _cmd_evt.info("clear confirmed action=%s", pending.action, chat_id=message.chat_id)
        if pending.action == "branch":
            return self._clear_branches(ctx)
        if pending.action == "worktrees":
            return self._clear_worktrees(ctx)
        if pending.action == "memory":
            return self._clear_memory(ctx, message.chat_id)
        return "알 수 없는 clear 작업입니다."

    def _bound_project_record(self, ctx: CommandContext) -> ProjectRecord | None:
        name = ctx.project_name
        if not name:
            return None
        return ctx.project_registry.get(name)

    def _clear_branches(self, ctx: CommandContext) -> str:
        p = self._bound_project_record(ctx)
        if p is None:
            return "봇에 연결된 프로젝트가 없거나 레지스트리에서 찾을 수 없습니다."
        if not p.enabled:
            return f"프로젝트가 비활성화되어 있습니다: {p.name}"

        try:
            ctx.git_service.checkout_integrate_branch(p.root_path)
            remote_branches = ctx.git_service.list_remote_branches_matching(
                p.root_path, ctx.git_remote_name, "remote-"
            )
            local_branches = ctx.git_service.list_local_branches_matching(p.root_path, "remote-")
            if remote_branches:
                ctx.git_service.delete_remote_branches(p.root_path, ctx.git_remote_name, remote_branches)
            if local_branches:
                ctx.git_service.remove_linked_worktrees_for_branches(p.root_path, local_branches)
                ctx.git_service.delete_local_branches(p.root_path, local_branches)
            return (
                f"{p.name}: 원격 {len(remote_branches)}개, 로컬 {len(local_branches)}개 삭제 "
                f"({ctx.git_remote_name})"
            )
        except RuntimeError as exc:
            return f"{p.name}: 실패 — {exc}"

    def _clear_memory(self, ctx: CommandContext, chat_id: int) -> str:
        if ctx.conversation_store is None:
            return "기억 저장소가 설정되지 않았습니다."
        project_name = ctx.project_name
        if not project_name:
            return "봇에 연결된 프로젝트가 없습니다."
        entries_removed, links_removed = ctx.conversation_store.delete_chat_memory(
            project=project_name, chat_id=chat_id
        )
        return (
            f"이 채팅방의 대화 기억을 삭제했습니다. "
            f"(project={project_name}, 대화 {entries_removed}건, 브랜치 연결 {links_removed}건)"
        )

    def _clear_worktrees(self, ctx: CommandContext) -> str:
        p = self._bound_project_record(ctx)
        if p is None:
            return "봇에 연결된 프로젝트가 없거나 레지스트리에서 찾을 수 없습니다."
        if not p.enabled:
            return f"프로젝트가 비활성화되어 있습니다: {p.name}"

        try:
            removed_count = ctx.git_service.cleanup_managed_worktrees(
                p.root_path,
                p.worktree_base_dir,
                branch_prefix="remote-",
            )
            return f"{p.name}: worktree {removed_count}개 삭제, stale prune 완료"
        except RuntimeError as exc:
            return f"{p.name}: 실패 — {exc}"


class StopCommand(TelegramCommand):
    name = "/stop"
    description = "진행 중인 Job을 선택해 중단합니다"

    def execute(self, message: TelegramMessage, ctx: CommandContext) -> str:
        tokens = message.text.strip().split(maxsplit=1)
        if len(tokens) < 2:
            jobs = self._list_cancellable_jobs(message, ctx)
            if not jobs:
                return "중단할 수 있는 진행 중 Job이 없습니다."
            return "중단할 Job을 선택하세요."
        job_id = tokens[1].strip()
        project_name = effective_project_name_for_chat(ctx, message.chat_id)
        existing = ctx.job_store.get(job_id)
        if existing is not None and project_name and existing.request.project != project_name:
            return f"Job을 찾을 수 없습니다: {job_id}"
        if ctx.job_manager is None:
            return "작업 중단 기능을 사용할 수 없습니다."
        success = ctx.job_manager.cancel(job_id)
        if success:
            return f"작업 중단 요청 완료: {job_id}"
        job = ctx.job_store.get(job_id)
        if not job:
            return f"Job을 찾을 수 없습니다: {job_id}"
        return f"작업을 중단할 수 없습니다: {job_id} (현재 상태: {job.status.value})"

    def get_inline_buttons(
        self,
        message: TelegramMessage | None = None,
        ctx: CommandContext | None = None,
    ) -> list[list[InlineButton]] | None:
        if message is None or ctx is None:
            return None
        if len(message.text.strip().split()) != 1:
            return None
        jobs = self._list_cancellable_jobs(message, ctx)
        if not jobs:
            return None
        return _button_rows(
            [InlineButton(_job_button_label(job), f"/stop {job.id}") for job in jobs],
            per_row=1,
        )

    @staticmethod
    def _list_cancellable_jobs(message: TelegramMessage, ctx: CommandContext) -> list[Job]:
        project_name = effective_project_name_for_chat(ctx, message.chat_id)
        if not project_name:
            return []
        return [
            job
            for job in ctx.job_store.list_recent_for_project_chat(
                project_name, message.chat_id, 20
            )
            if job.status in {JobStatus.QUEUED, JobStatus.RUNNING}
        ]


class CommandRegistry:
    def __init__(self, commands: list[TelegramCommand]) -> None:
        self._commands = {command.name: command for command in commands}
        help_cmd = self._commands.get("/help")
        if isinstance(help_cmd, HelpCommand):
            help_cmd._registry = self._commands

    def dispatch(self, message: TelegramMessage, ctx: CommandContext) -> str | None:
        tokens = message.text.strip().split()
        head = tokens[0] if tokens else ""
        # `/init`은 확인 대기보다 우선합니다. 대기 중이던 확인은 취소·삭제한 뒤 초기화합니다.
        scope_project = ctx.project_name

        if head == "/init":
            init_cmd = self._commands.get("/init")
            if init_cmd is not None:
                ctx.confirmation_store.pop(scope_project, message.chat_id)
                return init_cmd.execute(message, ctx)

        if head in {"/plan", "/ask"}:
            return None

        pending = ctx.confirmation_store.get(scope_project, message.chat_id)
        if pending is not None:
            command = self._commands.get(pending.command_name)
            confirmed = ctx.confirmation_store.pop(scope_project, message.chat_id)
            if isinstance(command, ConfirmableCommand) and confirmed is not None:
                return command.confirm(message, ctx, confirmed)
            return "확인 대기 작업을 처리할 수 없습니다."

        if not head.startswith("/"):
            return None
        command = self._commands.get(head)
        if not command:
            return "알 수 없는 명령어입니다. /help 를 확인하세요."
        return command.execute(message, ctx)

    def dispatch_rich(self, message: TelegramMessage, ctx: CommandContext) -> CommandResponse | None:
        text = self.dispatch(message, ctx)
        if text is None:
            return None
        tokens = message.text.strip().split()
        head = tokens[0] if tokens else ""
        command = self._commands.get(head)
        buttons = command.get_inline_buttons(message, ctx) if command is not None else None
        return CommandResponse(text=text, inline_buttons=buttons)

    def bot_commands(self) -> list[dict[str, str]]:
        base = [
            {"command": command.name.removeprefix("/"), "description": command.description}
            for command in self._commands.values()
            if command.description
        ]
        return base + [
            {
                "command": "plan",
                "description": "계획 모드 메시지 (예: /plan 로그인 흐름 검토)",
            },
            {
                "command": "ask",
                "description": "질문 모드 메시지 (예: /ask JobManager 역할 설명)",
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
    ]


def default_telegram_bot_commands() -> list[dict[str, str]]:
    return CommandRegistry(build_default_commands()).bot_commands()
