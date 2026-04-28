from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.git.service import GitWorktreeService
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
    git_service: GitWorktreeService
    git_remote_name: str


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
            "/branches\n"
            "/branch 또는 /branch <브랜치이름> (현재 브랜치 조회 / git switch)\n"
            "/rebase 또는 /rebase <branch>\n"
            "/clear\n"
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


class BranchesCommand(TelegramCommand):
    """기본 프로젝트 Git 저장소의 로컬·원격 브랜치 목록."""

    name = "/branches"

    _TELEGRAM_SAFE_LEN = 3800

    def execute(self, message: TelegramMessage, ctx: CommandContext) -> str:
        tokens = message.text.strip().split()
        if len(tokens) != 1:
            return "사용법: /branches"

        default_name = ctx.project_registry.get_default_project_name()
        if not default_name:
            return "기본 프로젝트가 없습니다. /projects 로 등록 후 기본 프로젝트를 지정하세요."
        entry = ctx.project_registry.get(default_name)
        if not entry or not entry.enabled:
            return "기본 프로젝트를 찾을 수 없거나 비활성화되어 있습니다."

        try:
            local_block = ctx.git_service.format_local_branches(entry.root_path)
            remote_block = ctx.git_service.format_remote_branches_for_remote(
                entry.root_path, ctx.git_remote_name
            )
        except RuntimeError as exc:
            return f"/branches 실패: {exc}"

        header = f"프로젝트: {default_name}\nroot: {entry.root_path}\n원격: {ctx.git_remote_name}\n\n"
        body = f"[로컬]\n{local_block}\n\n[{ctx.git_remote_name} 원격]\n{remote_block}"
        text = header + body
        if len(text) > self._TELEGRAM_SAFE_LEN:
            text = text[: self._TELEGRAM_SAFE_LEN].rstrip() + "\n\n...(메시지 길이 제한으로 생략)"
        return text


class BranchCommand(TelegramCommand):
    """기본 프로젝트 저장소의 현재 브랜치 조회 또는 `git switch`로 전환."""

    name = "/branch"

    def execute(self, message: TelegramMessage, ctx: CommandContext) -> str:
        tokens = message.text.strip().split()
        if len(tokens) > 2:
            return "사용법: /branch 또는 /branch <브랜치이름>"

        default_name = ctx.project_registry.get_default_project_name()
        if not default_name:
            return "기본 프로젝트가 없습니다. /projects 로 등록 후 기본 프로젝트를 지정하세요."
        entry = ctx.project_registry.get(default_name)
        if not entry or not entry.enabled:
            return "기본 프로젝트를 찾을 수 없거나 비활성화되어 있습니다."

        root = entry.root_path

        if len(tokens) == 1:
            try:
                current = ctx.git_service.get_current_branch(root)
            except RuntimeError as exc:
                return f"/branch 실패: {exc}"
            return f"프로젝트: {default_name}\n현재 브랜치: {current}"

        branch = tokens[1]
        err = GitWorktreeService.validate_branch_token(branch)
        if err:
            return err

        if not ctx.git_service.local_branch_exists(root, branch):
            return f"브랜치가 없습니다: `{branch}` (로컬에만 전환 가능합니다)"

        try:
            ctx.git_service.switch_branch(root, branch)
        except RuntimeError as exc:
            return f"/branch 실패: {exc}"
        return f"프로젝트: {default_name}\n`{branch}` 로 전환했습니다 (git switch)."


class RebaseCommand(TelegramCommand):
    """기본 프로젝트 저장소에서 브랜치를 main 기준으로 rebase 후 main에 fast-forward 병합·push."""

    name = "/rebase"

    def execute(self, message: TelegramMessage, ctx: CommandContext) -> str:
        tokens = message.text.strip().split()
        if len(tokens) > 2:
            return "사용법: /rebase 또는 /rebase <branch>"
        if len(tokens) == 2:
            branch = tokens[1]
        else:
            branch = ctx.job_store.get_latest_succeeded_branch_for_chat(message.chat_id)
            if not branch:
                return "최근 성공한 Job의 브랜치가 없습니다. /rebase <branch> 로 지정하세요."

        default_name = ctx.project_registry.get_default_project_name()
        if not default_name:
            return "기본 프로젝트가 없습니다. /projects 로 등록 후 기본 프로젝트를 지정하세요."
        entry = ctx.project_registry.get(default_name)
        if not entry or not entry.enabled:
            return "기본 프로젝트를 찾을 수 없거나 비활성화되어 있습니다."

        ops_base = entry.worktree_base_dir / "_rebase_ops"
        try:
            summary = ctx.git_service.rebase_branch_onto_main_and_merge(
                entry.root_path,
                branch,
                ctx.git_remote_name,
                ops_base,
            )
            return summary
        except RuntimeError as exc:
            return f"/rebase 실패: {exc}"


class ClearCommand(TelegramCommand):
    """등록된 enabled 프로젝트에서 remote-* 로컬·원격 브랜치 삭제."""

    name = "/clear"

    def execute(self, message: TelegramMessage, ctx: CommandContext) -> str:
        _ = message
        lines: list[str] = []
        projects = [p for p in ctx.project_registry.list_projects() if p.enabled]
        if not projects:
            return "enabled 프로젝트가 없습니다."

        for p in projects:
            try:
                ctx.git_service.checkout_integrate_branch(p.root_path)
                remote_branches = ctx.git_service.list_remote_branches_matching(
                    p.root_path, ctx.git_remote_name, "remote-"
                )
                local_branches = ctx.git_service.list_local_branches_matching(p.root_path, "remote-")
                if remote_branches:
                    ctx.git_service.delete_remote_branches(p.root_path, ctx.git_remote_name, remote_branches)
                if local_branches:
                    ctx.git_service.delete_local_branches(p.root_path, local_branches)
                lines.append(
                    f"{p.name}: 원격 {len(remote_branches)}개, 로컬 {len(local_branches)}개 삭제 "
                    f"({ctx.git_remote_name})"
                )
            except RuntimeError as exc:
                lines.append(f"{p.name}: 실패 — {exc}")
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
