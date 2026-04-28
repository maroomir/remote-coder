from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.jobs.store import InMemoryJobStore
from app.models import ModelName
from app.projects.registry import ProjectRegistry
from app.telegram.model_preferences import InMemoryModelPreferenceStore


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


class TelegramCommand(ABC):
    name: str

    @abstractmethod
    def execute(self, message: TelegramMessage, ctx: CommandContext) -> str:
        raise NotImplementedError


class StartCommand(TelegramCommand):
    name = "/start"

    def execute(self, message: TelegramMessage, ctx: CommandContext) -> str:
        _ = (message, ctx)
        return "Remote AI Coder에 오신 것을 환영합니다. /help 로 사용 가능한 명령어를 확인하세요."


class HelpCommand(TelegramCommand):
    name = "/help"

    def execute(self, message: TelegramMessage, ctx: CommandContext) -> str:
        _ = (message, ctx)
        return (
            "사용 가능한 명령어\n"
            "/start\n/help\n/model\n/model claude\n/model codex\n"
            "/status <job_id>\n/projects\n"
            "또는 자연어 지시문을 입력하세요. "
            "(옵션: model:, branch:, project:, no commit)"
        )


class ModelCommand(TelegramCommand):
    name = "/model"

    def execute(self, message: TelegramMessage, ctx: CommandContext) -> str:
        tokens = message.text.strip().split()
        current = ctx.model_preferences.get(message.chat_id)
        if len(tokens) == 1:
            return f"현재 기본 모델: {current.value}"
        if len(tokens) == 2 and tokens[1] in (ModelName.CLAUDE.value, ModelName.CODEX.value):
            selected = ModelName(tokens[1])
            ctx.model_preferences.set(message.chat_id, selected)
            return f"기본 모델이 {selected.value}로 변경되었습니다."
        return "사용법: /model 또는 /model claude|codex"


class StatusCommand(TelegramCommand):
    name = "/status"

    def execute(self, message: TelegramMessage, ctx: CommandContext) -> str:
        tokens = message.text.strip().split()
        if len(tokens) != 2:
            return "사용법: /status <job_id>"
        job = ctx.job_store.get(tokens[1])
        if not job:
            return "해당 Job ID를 찾을 수 없습니다."
        return f"Job {job.id} 상태: {job.status.value}"


class ProjectsCommand(TelegramCommand):
    name = "/projects"

    def execute(self, message: TelegramMessage, ctx: CommandContext) -> str:
        _ = message
        default_name = ctx.project_registry.get_default_project_name()
        lines = [f"기본 프로젝트: {default_name or '(없음)'}", "등록된 프로젝트"]
        for p in ctx.project_registry.list_projects():
            state = "on" if p.enabled else "off"
            lines.append(f"- {p.name} [{state}] root={p.root_path}")
        return "\n".join(lines)


class CommandRegistry:
    def __init__(self, commands: list[TelegramCommand]) -> None:
        self._commands = {command.name: command for command in commands}

    def dispatch(self, message: TelegramMessage, ctx: CommandContext) -> str | None:
        head = message.text.strip().split()[0] if message.text.strip() else ""
        if not head.startswith("/"):
            return None
        command = self._commands.get(head)
        if not command:
            return "알 수 없는 명령어입니다. /help 를 확인하세요."
        return command.execute(message, ctx)
