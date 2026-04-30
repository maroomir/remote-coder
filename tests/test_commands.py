from unittest.mock import Mock

from app.jobs.schemas import Job, JobRequest, JobStatus
from app.jobs.store import InMemoryJobStore
from app.models import ModelName
from app.projects.registry import ProjectRecord, ProjectRegistry
from app.telegram.commands import (
    BranchCommand,
    BranchesCommand,
    ClearCommand,
    CommandContext,
    CommandRegistry,
    HelpCommand,
    ModelCommand,
    ProjectCommand,
    ProjectsCommand,
    RebaseCommand,
    StartCommand,
    StatusCommand,
    TelegramMessage,
)
from app.telegram.confirmations import InMemoryConfirmationStore
from app.telegram.conversation import SQLiteConversationStore
from app.telegram.model_preferences import InMemoryModelPreferenceStore
from app.telegram.project_preferences import InMemoryProjectPreferenceStore


def _ctx(
    project_registry: ProjectRegistry,
    conversation_store: SQLiteConversationStore | None = None,
) -> CommandContext:
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
        project_preferences=InMemoryProjectPreferenceStore(),
        git_service=git_service,
        git_remote_name="origin",
        conversation_store=conversation_store,
        confirmation_store=InMemoryConfirmationStore(),
    )


def test_help_command_dispatch(project_registry: ProjectRegistry):
    registry = CommandRegistry(
        [
            StartCommand(),
            HelpCommand(),
            ModelCommand(),
            StatusCommand(),
            ProjectsCommand(),
            ProjectCommand(),
            BranchesCommand(),
            BranchCommand(),
            RebaseCommand(),
            ClearCommand(),
        ]
    )
    text = registry.dispatch(TelegramMessage(chat_id=1, user_id=1, text="/help"), _ctx(project_registry))
    assert text is not None
    assert text.startswith("도움말")
    assert "기본 명령" in text
    assert "프로젝트와 Git" in text
    assert "/status <job_id>: 작업 상태를 조회합니다." in text
    assert "/project <프로젝트이름>: 현재 채팅의 작업 프로젝트를 변경합니다." in text
    assert "/rebase [브랜치이름]: 브랜치를 main 기준으로 rebase 후 병합합니다." in text
    assert "자연어 작업 요청" in text
    assert "옵션: project:, model:, branch:, no commit" in text


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


def test_model_command_returns_consistent_usage(project_registry: ProjectRegistry):
    registry = CommandRegistry([ModelCommand()])
    text = registry.dispatch(TelegramMessage(chat_id=77, user_id=1, text="/model nope"), _ctx(project_registry))
    assert text == "사용법:\n/model\n/model <claude|codex>"


def test_projects_command_lists_registry(project_registry: ProjectRegistry):
    registry = CommandRegistry([ProjectsCommand()])
    text = registry.dispatch(TelegramMessage(chat_id=1, user_id=1, text="/projects"), _ctx(project_registry))
    assert text is not None
    assert "remote-coder" in text
    assert "기본 프로젝트" in text
    assert "현재 적용 프로젝트" in text


def test_project_command_shows_default_when_no_chat_preference(project_registry: ProjectRegistry):
    registry = CommandRegistry([ProjectCommand()])
    text = registry.dispatch(TelegramMessage(chat_id=5, user_id=1, text="/project"), _ctx(project_registry))
    assert text is not None
    assert "현재 작업 프로젝트" in text
    assert "remote-coder" in text


def test_project_command_switches_chat_preference(project_registry: ProjectRegistry):
    root = project_registry.config_path.parent / "other_repo"
    root.mkdir()
    wt = project_registry.config_path.parent / "other_wt"
    wt.mkdir()
    project_registry.add_project(
        ProjectRecord(
            name="other",
            root_path=root,
            worktree_base_dir=wt,
            default_model=ModelName.CODEX,
            enabled=True,
        )
    )
    registry = CommandRegistry([ProjectCommand(), ProjectsCommand()])
    ctx = _ctx(project_registry)
    text = registry.dispatch(TelegramMessage(chat_id=88, user_id=1, text="/project other"), ctx)
    assert text is not None and "other" in text and "변경" in text
    current = registry.dispatch(TelegramMessage(chat_id=88, user_id=1, text="/project"), ctx)
    assert current is not None and "other" in current


def test_project_command_unknown_project(project_registry: ProjectRegistry):
    registry = CommandRegistry([ProjectCommand()])
    text = registry.dispatch(
        TelegramMessage(chat_id=1, user_id=1, text="/project nope"),
        _ctx(project_registry),
    )
    assert text is not None and "알 수 없는" in text


def test_project_command_rejects_disabled_project(project_registry: ProjectRegistry):
    root = project_registry.config_path.parent / "off_repo"
    root.mkdir()
    wt = project_registry.config_path.parent / "off_wt"
    wt.mkdir()
    project_registry.add_project(
        ProjectRecord(
            name="offproj",
            root_path=root,
            worktree_base_dir=wt,
            enabled=False,
        )
    )
    registry = CommandRegistry([ProjectCommand()])
    text = registry.dispatch(
        TelegramMessage(chat_id=1, user_id=1, text="/project offproj"),
        _ctx(project_registry),
    )
    assert text is not None and "비활성화" in text


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
    assert text == "사용법:\n/branch\n/branch <브랜치이름>"


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


def test_clear_branch_command_requests_confirmation(project_registry: ProjectRegistry):
    ctx = _ctx(project_registry)
    registry = CommandRegistry([ClearCommand()])
    text = registry.dispatch(TelegramMessage(chat_id=1, user_id=1, text="/clear branch"), ctx)
    assert "현재 할 작업" in (text or "")
    assert "remote-*" in (text or "")
    ctx.git_service.delete_remote_branches.assert_not_called()
    ctx.git_service.delete_local_branches.assert_not_called()


def test_clear_branch_confirmation_executes_matching_deletes(project_registry: ProjectRegistry):
    ctx = _ctx(project_registry)
    ctx.git_service.list_remote_branches_matching.return_value = ["remote-x"]
    ctx.git_service.list_local_branches_matching.return_value = ["remote-y"]
    registry = CommandRegistry([ClearCommand()])
    registry.dispatch(TelegramMessage(chat_id=1, user_id=1, text="/clear branch"), ctx)
    text = registry.dispatch(TelegramMessage(chat_id=1, user_id=1, text="y"), ctx)
    assert "remote-coder" in (text or "")
    assert "원격 1개" in (text or "")
    assert "로컬 1개" in (text or "")
    assert "(origin)" in (text or "")
    ctx.git_service.checkout_integrate_branch.assert_called()
    ctx.git_service.delete_remote_branches.assert_called_once()
    ctx.git_service.remove_linked_worktrees_for_branches.assert_called_once()
    ctx.git_service.delete_local_branches.assert_called_once()


def test_clear_confirmation_rejects_non_yes(project_registry: ProjectRegistry):
    ctx = _ctx(project_registry)
    registry = CommandRegistry([ClearCommand()])
    registry.dispatch(TelegramMessage(chat_id=1, user_id=1, text="/clear branch"), ctx)
    text = registry.dispatch(TelegramMessage(chat_id=1, user_id=1, text="n"), ctx)
    assert text == "브랜치 삭제를 취소했습니다."
    ctx.git_service.delete_remote_branches.assert_not_called()
    ctx.git_service.delete_local_branches.assert_not_called()


def test_clear_memory_confirmation_resets_conversation_db(
    project_registry: ProjectRegistry,
    tmp_path,
):
    db = tmp_path / "conv.sqlite3"
    conversation_store = SQLiteConversationStore(db)
    conversation_store.append(project="remote-coder", chat_id=1, role="user", text="hello", job_id=None)
    ctx = _ctx(project_registry, conversation_store=conversation_store)
    registry = CommandRegistry([ClearCommand()])

    prompt = registry.dispatch(TelegramMessage(chat_id=1, user_id=1, text="/clear memory"), ctx)
    text = registry.dispatch(TelegramMessage(chat_id=1, user_id=1, text="Y"), ctx)

    assert "SQLite" in (prompt or "")
    assert text == "대화 기억 SQLite 데이터베이스를 초기화했습니다."
    assert conversation_store.list_recent("remote-coder", 1, 10) == []
