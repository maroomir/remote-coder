from pathlib import Path
from unittest.mock import Mock, patch

from app.jobs.schemas import Job, JobRequest, JobStatus
from app.jobs.store import InMemoryJobStore
from app.models import ModelName
from app.projects.registry import ProjectRecord, ProjectRegistry
from app.telegram.commands import (
    BranchCommand,
    ClearCommand,
    CommandContext,
    CommandRegistry,
    HelpCommand,
    InitCommand,
    ModelCommand,
    MonitorCommand,
    ProjectCommand,
    ProjectsCommand,
    ReportsCommand,
    RebaseCommand,
    StartCommand,
    StatusCommand,
    TelegramMessage,
    InlineButton,
)
from app.telegram.confirmations import InMemoryConfirmationStore, PendingConfirmation
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
            InitCommand(),
            ReportsCommand(),
            BranchCommand(),
            RebaseCommand(),
            MonitorCommand(),
            ClearCommand(),
        ]
    )
    text = registry.dispatch(TelegramMessage(chat_id=1, user_id=1, text="/help"), _ctx(project_registry))
    assert text is not None
    assert text.startswith("도움말")
    assert "기본 명령" in text
    assert "프로젝트와 Git" in text
    assert "모니터링" in text
    assert "정리 및 초기화" in text
    assert "/clear branch:" in text
    assert "/status <job_id>: 작업 상태를 조회합니다." in text
    assert "/project <프로젝트이름>: 현재 채팅의 작업 프로젝트를 변경합니다." in text
    assert "/init:" in text
    assert "/rebase [브랜치이름]: 적용 프로젝트에서 브랜치를 main 기준으로 rebase 후 병합합니다." in text
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


def test_model_command_updates_preference_to_gemini(project_registry: ProjectRegistry):
    registry = CommandRegistry([ModelCommand()])
    ctx = _ctx(project_registry)
    text = registry.dispatch(TelegramMessage(chat_id=77, user_id=1, text="/model gemini"), ctx)
    assert text == "기본 모델이 gemini로 변경되었습니다."
    assert ctx.model_preferences.get(77) == ModelName.GEMINI


def test_model_command_returns_consistent_usage(project_registry: ProjectRegistry):
    registry = CommandRegistry([ModelCommand()])
    text = registry.dispatch(TelegramMessage(chat_id=77, user_id=1, text="/model nope"), _ctx(project_registry))
    assert text == "사용법:\n/model\n/model <claude|codex|gemini>"


def test_projects_command_lists_registry(project_registry: ProjectRegistry):
    registry = CommandRegistry([ProjectsCommand()])
    text = registry.dispatch(TelegramMessage(chat_id=1, user_id=1, text="/projects"), _ctx(project_registry))
    assert text is not None
    assert "remote-coder" in text
    assert "이 채팅 적용 프로젝트" in text


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


def test_init_command_resets_project_model_and_pending(project_registry: ProjectRegistry):
    root = project_registry.config_path.parent / "init_other_repo"
    root.mkdir()
    wt = project_registry.config_path.parent / "init_other_wt"
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
    registry = CommandRegistry([InitCommand(), ClearCommand(), ModelCommand(), ProjectCommand()])
    ctx = _ctx(project_registry)
    chat_id = 42
    ctx.project_preferences.set(chat_id, "other")
    ctx.model_preferences.set(chat_id, ModelName.CODEX)
    ctx.confirmation_store.set(chat_id, PendingConfirmation(command_name="/clear", action="memory"))

    text = registry.dispatch(TelegramMessage(chat_id=chat_id, user_id=1, text="/init"), ctx)
    assert text is not None
    assert "초기화했습니다" in text
    assert "적용 프로젝트: remote-coder" in text
    assert "기본 모델: claude" in text
    assert ctx.project_preferences.get(chat_id) is None
    assert ctx.model_preferences.get(chat_id) == ModelName.CLAUDE
    assert ctx.confirmation_store.get(chat_id) is None


def test_init_command_runs_when_clear_confirmation_pending(project_registry: ProjectRegistry):
    """`/init`은 확인 대기보다 우선하며, 대기 중인 `/clear` 확인을 버리고 초기화합니다."""
    registry = CommandRegistry([InitCommand(), ClearCommand()])
    ctx = _ctx(project_registry)
    chat_id = 99
    ctx.confirmation_store.set(chat_id, PendingConfirmation(command_name="/clear", action="memory"))

    text = registry.dispatch(TelegramMessage(chat_id=chat_id, user_id=1, text="/init"), ctx)
    assert text is not None and "초기화했습니다" in text
    assert ctx.confirmation_store.get(chat_id) is None


def test_init_command_rejects_extra_args(project_registry: ProjectRegistry):
    registry = CommandRegistry([InitCommand()])
    text = registry.dispatch(
        TelegramMessage(chat_id=1, user_id=1, text="/init extra"),
        _ctx(project_registry),
    )
    assert text == "사용법:\n/init"


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


def test_clear_worktrees_command_requests_confirmation(project_registry: ProjectRegistry):
    ctx = _ctx(project_registry)
    registry = CommandRegistry([ClearCommand()])
    text = registry.dispatch(TelegramMessage(chat_id=1, user_id=1, text="/clear worktrees"), ctx)
    assert "현재 할 작업" in (text or "")
    assert "stale" in (text or "")
    ctx.git_service.cleanup_managed_worktrees.assert_not_called()


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


def test_clear_worktrees_confirmation_executes_cleanup(project_registry: ProjectRegistry):
    ctx = _ctx(project_registry)
    ctx.git_service.cleanup_managed_worktrees.return_value = 2
    registry = CommandRegistry([ClearCommand()])
    registry.dispatch(TelegramMessage(chat_id=1, user_id=1, text="/clear worktrees"), ctx)
    text = registry.dispatch(TelegramMessage(chat_id=1, user_id=1, text="y"), ctx)
    assert "remote-coder" in (text or "")
    assert "worktree 2개 삭제" in (text or "")
    assert "prune 완료" in (text or "")
    ctx.git_service.cleanup_managed_worktrees.assert_called_once()


def test_reports_command_summarizes_sqlite_memory(project_registry: ProjectRegistry, tmp_path):
    db = tmp_path / "cmd_reports.sqlite3"
    conversation_store = SQLiteConversationStore(db)
    conversation_store.append(
        project="remote-coder",
        chat_id=77,
        role="user",
        text="README 수정해줘",
        job_id=None,
    )
    conversation_store.append(
        project="remote-coder",
        chat_id=77,
        role="job_result",
        text="status=succeeded",
        job_id="job-7",
    )
    ctx = _ctx(project_registry)
    ctx.conversation_store = conversation_store
    registry = CommandRegistry([ReportsCommand()])

    text = registry.dispatch(TelegramMessage(chat_id=77, user_id=1, text="/reports"), ctx)

    assert text is not None
    assert "기억 리포트" in text
    assert "총 기록: 2개" in text
    assert "최근 사용자 요청: README 수정해줘" in text
    assert "job-7" in text


def test_reports_command_handles_empty_memory(project_registry: ProjectRegistry, tmp_path):
    db = tmp_path / "cmd_reports_empty.sqlite3"
    ctx = _ctx(project_registry)
    ctx.conversation_store = SQLiteConversationStore(db)
    registry = CommandRegistry([ReportsCommand()])

    text = registry.dispatch(TelegramMessage(chat_id=77, user_id=1, text="/reports"), ctx)

    assert text == "기억된 대화 기록이 없습니다. (project=remote-coder)"


def test_monitor_command_shows_usage(project_registry: ProjectRegistry):
    registry = CommandRegistry([MonitorCommand()])
    text = registry.dispatch(TelegramMessage(chat_id=1, user_id=1, text="/monitor"), _ctx(project_registry))
    assert text is not None
    assert "사용법" in text
    assert "/monitor" in text


def test_monitor_command_rejects_invalid_subcommand(project_registry: ProjectRegistry):
    registry = CommandRegistry([MonitorCommand()])
    text = registry.dispatch(
        TelegramMessage(chat_id=1, user_id=1, text="/monitor nope"),
        _ctx(project_registry),
    )
    assert text is not None
    assert "사용법" in text


def test_monitor_memory_shows_sqlite_stats(project_registry: ProjectRegistry, tmp_path):
    db = tmp_path / "monitor_mem.sqlite3"
    store = SQLiteConversationStore(db)
    store.append(project="remote-coder", chat_id=42, role="user", text="hi", job_id=None)
    ctx = _ctx(project_registry)
    ctx.conversation_store = store
    registry = CommandRegistry([MonitorCommand()])
    text = registry.dispatch(TelegramMessage(chat_id=42, user_id=1, text="/monitor memory"), ctx)
    assert text is not None
    assert "메모리(SQLite)" in text
    assert "이 채팅 저장 행 수: 1" in text
    assert "user=1" in text


def test_monitor_branch_uses_git_service(project_registry: ProjectRegistry):
    ctx = _ctx(project_registry)
    ctx.git_service.get_current_branch.return_value = "main"
    ctx.git_service.count_local_branches.return_value = 2
    ctx.git_service.count_remote_branches_for_remote.return_value = 1
    ctx.git_service.format_local_branches.return_value = "* main"
    ctx.git_service.format_remote_branches_for_remote.return_value = "origin/main"
    registry = CommandRegistry([MonitorCommand()])
    text = registry.dispatch(TelegramMessage(chat_id=1, user_id=1, text="/monitor branch"), ctx)
    assert text is not None
    assert "브랜치 모니터" in text
    ctx.git_service.count_local_branches.assert_called_once()


def test_monitor_worktrees_lists_entries(project_registry: ProjectRegistry):
    ctx = _ctx(project_registry)
    ctx.git_service.list_worktree_entries.return_value = [
        (Path("/fake/repo"), "main"),
        (Path("/fake/repo/wt"), None),
    ]
    registry = CommandRegistry([MonitorCommand()])
    text = registry.dispatch(TelegramMessage(chat_id=1, user_id=1, text="/monitor worktrees"), ctx)
    assert text is not None
    assert "워크트리 모니터" in text
    assert "detached" in text


def test_monitor_model_invokes_claude_probe(project_registry: ProjectRegistry):
    ctx = _ctx(project_registry)
    job = ctx.job_store.get("job1")
    assert job is not None
    job.status = JobStatus.SUCCEEDED
    job.runner_stdout_summary = "model: Claude Opus 4.7\ninput tokens: 100\noutput tokens: 25"
    ctx.job_store.update(job)
    with patch("app.monitoring.model.subprocess.run") as mock_run:
        mock_run.return_value = Mock(returncode=0, stdout="Logged in\n", stderr="")
        registry = CommandRegistry([MonitorCommand()])
        text = registry.dispatch(
            TelegramMessage(chat_id=1, user_id=1, text="/monitor model"),
            ctx,
        )
    assert text is not None
    assert "현재 채팅 기본 모델: claude" in text
    assert "[Claude]" in text
    assert "관측된 세부 모델: Claude Opus 4.7" in text
    assert "input=100" in text


def test_monitor_code_counts_lines(project_registry: ProjectRegistry, tmp_path):
    root = project_registry.config_path.parent / "count_repo"
    root.mkdir(parents=True)
    (root / "a.py").write_text("# x\nprint(1)\n", encoding="utf-8")
    project_registry.add_project(
        ProjectRecord(
            name="countproj",
            root_path=root,
            worktree_base_dir=tmp_path / "wt",
            enabled=True,
        )
    )
    project_registry.set_default_project("countproj")
    registry = CommandRegistry([MonitorCommand()])
    ctx = _ctx(project_registry)
    ctx.project_preferences.set(7, "countproj")
    text = registry.dispatch(TelegramMessage(chat_id=7, user_id=1, text="/monitor code"), ctx)
    assert text is not None
    assert "코드 규모" in text
    assert "스캔한 코드 파일 수: 1" in text


def test_help_command_get_inline_buttons():
    cmd = HelpCommand()
    buttons = cmd.get_inline_buttons()
    assert buttons is not None
    flat = [btn for row in buttons for btn in row]
    assert all(isinstance(b, InlineButton) for b in flat)
    data = {btn.callback_data for btn in flat}
    assert "/model claude" in data
    assert "/model codex" in data
    assert "/model gemini" in data
    assert "/monitor model" in data
    assert "/monitor memory" in data


def test_dispatch_rich_help_includes_buttons(project_registry: ProjectRegistry):
    registry = CommandRegistry([HelpCommand()])
    response = registry.dispatch_rich(
        TelegramMessage(chat_id=1, user_id=1, text="/help"),
        _ctx(project_registry),
    )
    assert response is not None
    assert response.text.startswith("도움말")
    assert response.inline_buttons is not None


def test_dispatch_rich_non_help_has_no_buttons(project_registry: ProjectRegistry):
    registry = CommandRegistry([ModelCommand()])
    response = registry.dispatch_rich(
        TelegramMessage(chat_id=1, user_id=1, text="/model"),
        _ctx(project_registry),
    )
    assert response is not None
    assert response.inline_buttons is None


def test_dispatch_rich_returns_none_for_natural_language(project_registry: ProjectRegistry):
    registry = CommandRegistry([ModelCommand()])
    response = registry.dispatch_rich(
        TelegramMessage(chat_id=1, user_id=1, text="자연어 메시지"),
        _ctx(project_registry),
    )
    assert response is None
