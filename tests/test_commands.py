from unittest.mock import Mock

from app.jobs.schemas import Job, JobRequest, JobStatus
from app.jobs.store import InMemoryJobStore
from app.models import ModelName
from app.projects.registry import ProjectRegistry
from app.telegram.commands import (
    BranchCommand,
    BranchesCommand,
    ClearCommand,
    CommandContext,
    CommandRegistry,
    HelpCommand,
    ModelCommand,
    ProjectsCommand,
    RebaseCommand,
    StartCommand,
    StatusCommand,
    TelegramMessage,
)
from app.telegram.model_preferences import InMemoryModelPreferenceStore


def _ctx(project_registry: ProjectRegistry) -> CommandContext:
    store = InMemoryJobStore()
    job = Job(
        id="job1",
        request=JobRequest(
            project="remote-coder",
            model=ModelName.CLAUDE,
            instruction="x",
            chat_id=1,
            requested_by=1,
        ),
        status=JobStatus.QUEUED,
    )
    store.create(job)
    git_service = Mock()
    return CommandContext(
        job_store=store,
        default_model=ModelName.CLAUDE,
        project_registry=project_registry,
        model_preferences=InMemoryModelPreferenceStore(default_model=ModelName.CLAUDE),
        git_service=git_service,
        git_remote_name="origin",
    )


def test_help_command_dispatch(project_registry: ProjectRegistry):
    registry = CommandRegistry(
        [
            StartCommand(),
            HelpCommand(),
            ModelCommand(),
            StatusCommand(),
            ProjectsCommand(),
            BranchesCommand(),
            BranchCommand(),
            RebaseCommand(),
            ClearCommand(),
        ]
    )
    text = registry.dispatch(TelegramMessage(chat_id=1, user_id=1, text="/help"), _ctx(project_registry))
    assert text is not None and "/status <job_id>" in text
    assert "project:" in text
    assert "/branches" in text
    assert "/branch" in text
    assert "/rebase" in text
    assert "/clear" in text


def test_status_command_dispatch(project_registry: ProjectRegistry):
    registry = CommandRegistry([StatusCommand()])
    text = registry.dispatch(
        TelegramMessage(chat_id=1, user_id=1, text="/status job1"),
        _ctx(project_registry),
    )
    assert text == "Job job1 상태: queued"


def test_model_command_updates_preference(project_registry: ProjectRegistry):
    registry = CommandRegistry([ModelCommand()])
    ctx = _ctx(project_registry)
    text = registry.dispatch(TelegramMessage(chat_id=77, user_id=1, text="/model codex"), ctx)
    assert text == "기본 모델이 codex로 변경되었습니다."
    current = registry.dispatch(TelegramMessage(chat_id=77, user_id=1, text="/model"), ctx)
    assert current == "현재 기본 모델: codex"


def test_projects_command_lists_registry(project_registry: ProjectRegistry):
    registry = CommandRegistry([ProjectsCommand()])
    text = registry.dispatch(TelegramMessage(chat_id=1, user_id=1, text="/projects"), _ctx(project_registry))
    assert text is not None
    assert "remote-coder" in text
    assert "기본 프로젝트" in text


def test_branches_command_shows_local_and_remote(project_registry: ProjectRegistry):
    ctx = _ctx(project_registry)
    ctx.git_service.format_local_branches.return_value = "* main\n  feature"
    ctx.git_service.format_remote_branches_for_remote.return_value = "origin/main"
    registry = CommandRegistry([BranchesCommand()])
    text = registry.dispatch(TelegramMessage(chat_id=1, user_id=1, text="/branches"), ctx)
    assert "remote-coder" in text
    assert "[로컬]" in text
    assert "* main" in text
    assert "[origin 원격]" in text
    assert "origin/main" in text
    ctx.git_service.format_local_branches.assert_called_once()
    ctx.git_service.format_remote_branches_for_remote.assert_called_once()


def test_branch_command_shows_current_branch(project_registry: ProjectRegistry):
    ctx = _ctx(project_registry)
    ctx.git_service.get_current_branch.return_value = "main"
    registry = CommandRegistry([BranchCommand()])
    text = registry.dispatch(TelegramMessage(chat_id=5, user_id=1, text="/branch"), ctx)
    assert "현재 브랜치" in text
    assert "main" in text
    ctx.git_service.get_current_branch.assert_called_once()


def test_branch_command_switches_when_local_exists(project_registry: ProjectRegistry):
    ctx = _ctx(project_registry)
    ctx.git_service.local_branch_exists.return_value = True
    registry = CommandRegistry([BranchCommand()])
    text = registry.dispatch(TelegramMessage(chat_id=5, user_id=1, text="/branch develop"), ctx)
    assert "develop" in text
    assert "전환" in text
    ctx.git_service.local_branch_exists.assert_called_once()
    ctx.git_service.switch_branch.assert_called_once()


def test_branch_command_missing_branch_error(project_registry: ProjectRegistry):
    ctx = _ctx(project_registry)
    ctx.git_service.local_branch_exists.return_value = False
    registry = CommandRegistry([BranchCommand()])
    text = registry.dispatch(TelegramMessage(chat_id=5, user_id=1, text="/branch nope"), ctx)
    assert "없습니다" in text
    ctx.git_service.switch_branch.assert_not_called()


def test_branch_command_rejects_invalid_token(project_registry: ProjectRegistry):
    ctx = _ctx(project_registry)
    registry = CommandRegistry([BranchCommand()])
    text = registry.dispatch(TelegramMessage(chat_id=5, user_id=1, text="/branch bad name"), ctx)
    assert "사용법" in text or "허용" in text or "이름" in text


def test_rebase_command_uses_latest_succeeded_branch(project_registry: ProjectRegistry):
    ctx = _ctx(project_registry)
    done = Job(
        id="done1",
        request=JobRequest(
            project="remote-coder",
            model=ModelName.CLAUDE,
            instruction="x",
            chat_id=99,
            requested_by=1,
        ),
        status=JobStatus.SUCCEEDED,
        branch="remote-abc",
    )
    ctx.job_store.create(done)
    ctx.git_service.rebase_branch_onto_main_and_merge.return_value = "rebase ok"

    registry = CommandRegistry([RebaseCommand()])
    text = registry.dispatch(TelegramMessage(chat_id=99, user_id=1, text="/rebase"), ctx)

    assert text == "rebase ok"
    ctx.git_service.rebase_branch_onto_main_and_merge.assert_called_once()
    args = ctx.git_service.rebase_branch_onto_main_and_merge.call_args[0]
    assert args[1] == "remote-abc"


def test_rebase_command_with_explicit_branch(project_registry: ProjectRegistry):
    ctx = _ctx(project_registry)
    ctx.git_service.rebase_branch_onto_main_and_merge.return_value = "ok"
    registry = CommandRegistry([RebaseCommand()])
    text = registry.dispatch(TelegramMessage(chat_id=1, user_id=1, text="/rebase my-feature"), ctx)
    assert text == "ok"
    assert ctx.git_service.rebase_branch_onto_main_and_merge.call_args[0][1] == "my-feature"


def test_rebase_command_no_recent_branch(project_registry: ProjectRegistry):
    ctx = _ctx(project_registry)
    registry = CommandRegistry([RebaseCommand()])
    text = registry.dispatch(TelegramMessage(chat_id=42, user_id=1, text="/rebase"), ctx)
    assert "없습니다" in (text or "")
    ctx.git_service.rebase_branch_onto_main_and_merge.assert_not_called()


def test_clear_command_deletes_matching_branches(project_registry: ProjectRegistry):
    ctx = _ctx(project_registry)
    ctx.git_service.list_remote_branches_matching.return_value = ["remote-x"]
    ctx.git_service.list_local_branches_matching.return_value = ["remote-y"]
    registry = CommandRegistry([ClearCommand()])
    text = registry.dispatch(TelegramMessage(chat_id=1, user_id=1, text="/clear"), ctx)
    assert "remote-coder" in (text or "")
    ctx.git_service.checkout_integrate_branch.assert_called()
    ctx.git_service.delete_remote_branches.assert_called_once()
    ctx.git_service.delete_local_branches.assert_called_once()
