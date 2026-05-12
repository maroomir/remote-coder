from pathlib import Path
from unittest.mock import Mock, patch

from app.admin.advanced_settings import AdvancedSettings
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
    ReportsCommand,
    RebaseCommand,
    StartCommand,
    StatusCommand,
    StopCommand,
    TelegramMessage,
    InlineButton,
    build_default_commands,
)
from app.telegram.confirmations import InMemoryConfirmationStore, PendingConfirmation
from app.telegram.conversation import SQLiteConversationStore
from app.telegram.model_preferences import InMemoryModelPreferenceStore


def _ctx(
    project_registry: ProjectRegistry,
    conversation_store: SQLiteConversationStore | None = None,
    advanced_settings_store: Mock | None = None,
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
        project_name=project_registry.get_default_project_name(),
        git_service=git_service,
        git_remote_name="origin",
        conversation_store=conversation_store,
        confirmation_store=InMemoryConfirmationStore(),
        advanced_settings_store=advanced_settings_store,
    )


def test_help_command_dispatch(project_registry: ProjectRegistry):
    registry = CommandRegistry(
        [
            StartCommand(),
            HelpCommand(),
            ModelCommand(),
            StatusCommand(),
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
    assert "작업 지시는 일반 메시지로 보내세요." in text
    assert "옵션\n- model:\n- branch:\n- no commit" in text
    assert "명령어 목록:" in text
    assert "/clear branch:" not in text


def test_default_bot_commands_expose_telegram_menu_entries():
    registry = CommandRegistry(build_default_commands())

    commands = registry.bot_commands()

    names = [item["command"] for item in commands]
    assert names == [
        "start",
        "help",
        "model",
        "status",
        "init",
        "reports",
        "branch",
        "pull",
        "rebase",
        "pr",
        "monitor",
        "clear",
        "stop",
    ]
    assert all("/" not in item["command"] for item in commands)
    assert all(item["description"] for item in commands)


def test_help_command_returns_text_with_no_buttons(project_registry: ProjectRegistry):
    registry = CommandRegistry([HelpCommand()])
    response = registry.dispatch_rich(TelegramMessage(chat_id=1, user_id=1, text="/help"), _ctx(project_registry))

    assert response is not None
    assert response.text.startswith("도움말")
    assert response.inline_buttons is None


def test_status_command_dispatch(project_registry: ProjectRegistry):
    registry = CommandRegistry([StatusCommand()])
    text = registry.dispatch(
        TelegramMessage(chat_id=1, user_id=1, text="/status job1"),
        _ctx(project_registry),
    )
    assert text is not None
    assert "job1" in text
    assert "queued" in text
    assert "프로젝트:" in text
    assert "모델:" in text


def test_status_command_lists_recent_jobs_as_buttons(project_registry: ProjectRegistry):
    registry = CommandRegistry([StatusCommand()])
    response = registry.dispatch_rich(
        TelegramMessage(chat_id=1, user_id=1, text="/status"),
        _ctx(project_registry),
    )

    assert response is not None
    assert response.text == "조회할 Job을 선택하세요."
    assert response.inline_buttons == [[InlineButton("job1 (queued)", "/status job1")]]


def test_model_command_updates_preference(project_registry: ProjectRegistry):
    registry = CommandRegistry([ModelCommand()])
    ctx = _ctx(project_registry)
    text = registry.dispatch(TelegramMessage(chat_id=77, user_id=1, text="/model codex"), ctx)
    assert text == "모델 설정이 변경되었습니다.\n\n- 기본 모델을 codex로 변경했습니다."
    current = registry.dispatch(TelegramMessage(chat_id=77, user_id=1, text="/model"), ctx)
    assert current == "모델 설정\n\n- 현재 기본 모델: codex"


def test_model_command_shows_model_buttons(project_registry: ProjectRegistry):
    registry = CommandRegistry([ModelCommand()])
    response = registry.dispatch_rich(TelegramMessage(chat_id=77, user_id=1, text="/model"), _ctx(project_registry))

    assert response is not None
    assert response.text == "모델 설정\n\n- 현재 기본 모델: claude"
    assert response.inline_buttons == [
        [
            InlineButton("claude", "/model claude"),
            InlineButton("codex", "/model codex"),
            InlineButton("gemini", "/model gemini"),
        ]
    ]


def test_model_command_keeps_model_buttons_after_selection(project_registry: ProjectRegistry):
    registry = CommandRegistry([ModelCommand()])
    response = registry.dispatch_rich(
        TelegramMessage(chat_id=77, user_id=1, text="/model codex"),
        _ctx(project_registry),
    )

    assert response is not None
    assert response.text == "모델 설정이 변경되었습니다.\n\n- 기본 모델을 codex로 변경했습니다."
    assert response.inline_buttons == [
        [
            InlineButton("claude", "/model claude"),
            InlineButton("codex", "/model codex"),
            InlineButton("gemini", "/model gemini"),
        ]
    ]


def test_model_command_updates_preference_to_gemini(project_registry: ProjectRegistry):
    registry = CommandRegistry([ModelCommand()])
    ctx = _ctx(project_registry)
    text = registry.dispatch(TelegramMessage(chat_id=77, user_id=1, text="/model gemini"), ctx)
    assert text == "모델 설정이 변경되었습니다.\n\n- 기본 모델을 gemini로 변경했습니다."
    assert ctx.model_preferences.get(ctx.project_name, 77) == ModelName.GEMINI


def test_model_command_returns_consistent_usage(project_registry: ProjectRegistry):
    registry = CommandRegistry([ModelCommand()])
    text = registry.dispatch(TelegramMessage(chat_id=77, user_id=1, text="/model nope"), _ctx(project_registry))
    assert text == "사용법\n\n- /model\n- /model <claude|codex|gemini>"


def test_monitor_project_lists_registry(project_registry: ProjectRegistry):
    registry = CommandRegistry([MonitorCommand()])
    text = registry.dispatch(TelegramMessage(chat_id=1, user_id=1, text="/monitor project"), _ctx(project_registry))
    assert text is not None
    assert "remote-coder" in text
    assert "이 봇 프로젝트" in text


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
            bot_token="123:other",
            allowed_chat_ids=[123],
        )
    )
    registry = CommandRegistry([InitCommand(), ClearCommand(), ModelCommand()])
    ctx = _ctx(project_registry)
    chat_id = 42
    ctx.project_name = "other"
    ctx.model_preferences.set("other", chat_id, ModelName.CODEX)
    ctx.confirmation_store.set(
        "other",
        chat_id,
        PendingConfirmation(command_name="/clear", action="memory"),
    )

    text = registry.dispatch(TelegramMessage(chat_id=chat_id, user_id=1, text="/init"), ctx)
    assert text is not None
    assert "초기화했습니다" in text
    assert "적용 프로젝트: other" in text
    assert "기본 모델: codex" in text
    assert ctx.model_preferences.get("other", chat_id) == ModelName.CLAUDE
    assert ctx.confirmation_store.get("other", chat_id) is None


def test_init_command_runs_when_clear_confirmation_pending(project_registry: ProjectRegistry):
    registry = CommandRegistry([InitCommand(), ClearCommand()])
    ctx = _ctx(project_registry)
    chat_id = 99
    pname = ctx.project_name
    ctx.confirmation_store.set(
        pname,
        chat_id,
        PendingConfirmation(command_name="/clear", action="memory"),
    )

    text = registry.dispatch(TelegramMessage(chat_id=chat_id, user_id=1, text="/init"), ctx)
    assert text is not None and "초기화했습니다" in text
    assert ctx.confirmation_store.get(pname, chat_id) is None


def test_init_command_rejects_extra_args(project_registry: ProjectRegistry):
    registry = CommandRegistry([InitCommand()])
    text = registry.dispatch(
        TelegramMessage(chat_id=1, user_id=1, text="/init extra"),
        _ctx(project_registry),
    )
    assert text == "사용법\n\n- /init"


def test_branch_command_shows_current_branch(project_registry: ProjectRegistry):
    ctx = _ctx(project_registry)
    ctx.git_service.get_current_branch.return_value = "main"
    registry = CommandRegistry([BranchCommand()])
    text = registry.dispatch(TelegramMessage(chat_id=5, user_id=1, text="/branch"), ctx)
    assert "현재 브랜치" in text
    assert "main" in text
    ctx.git_service.get_current_branch.assert_called_once()


def test_branch_command_lists_local_branch_buttons(project_registry: ProjectRegistry):
    ctx = _ctx(project_registry)
    ctx.git_service.get_current_branch.return_value = "main"
    ctx.git_service.list_local_branches.return_value = ["develop", "main"]
    registry = CommandRegistry([BranchCommand()])

    response = registry.dispatch_rich(TelegramMessage(chat_id=5, user_id=1, text="/branch"), ctx)

    assert response is not None
    assert response.inline_buttons == [
        [InlineButton("develop", "/branch develop")],
        [InlineButton("main", "/branch main")],
    ]


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
    assert text == "사용법\n\n- /branch\n- /branch <브랜치이름>"


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
    ctx.git_service.list_remote_branches_matching.return_value = ["remote-abc"]

    registry = CommandRegistry([RebaseCommand()])
    text = registry.dispatch(TelegramMessage(chat_id=99, user_id=1, text="/rebase remote-abc"), ctx)

    assert text == "rebase ok\n브랜치 `remote-abc`를 로컬과 `origin`에서 삭제했습니다."
    ctx.git_service.rebase_branch_onto_main_and_merge.assert_called_once()
    args = ctx.git_service.rebase_branch_onto_main_and_merge.call_args[0]
    assert args[1] == "remote-abc"
    ctx.git_service.delete_remote_branches.assert_called_once()
    ctx.git_service.delete_local_branches.assert_called_once()


def test_rebase_command_with_explicit_branch(project_registry: ProjectRegistry):
    ctx = _ctx(project_registry)
    ctx.git_service.rebase_branch_onto_main_and_merge.return_value = "ok"
    ctx.git_service.list_remote_branches_matching.return_value = ["my-feature"]
    registry = CommandRegistry([RebaseCommand()])
    text = registry.dispatch(TelegramMessage(chat_id=1, user_id=1, text="/rebase my-feature"), ctx)
    assert text == "ok\n브랜치 `my-feature`를 로컬과 `origin`에서 삭제했습니다."
    assert ctx.git_service.rebase_branch_onto_main_and_merge.call_args[0][1] == "my-feature"
    ctx.git_service.delete_remote_branches.assert_called_once()
    ctx.git_service.delete_local_branches.assert_called_once()


def test_rebase_command_reports_missing_remote_branch(project_registry: ProjectRegistry):
    ctx = _ctx(project_registry)
    ctx.git_service.list_remote_branches_matching.return_value = ["other-feature"]
    registry = CommandRegistry([RebaseCommand()])

    text = registry.dispatch(TelegramMessage(chat_id=1, user_id=1, text="/rebase stale-feature"), ctx)

    assert "`stale-feature` 원격 브랜치" in (text or "")
    assert "이미 rebase/병합 후 삭제" in (text or "")
    ctx.git_service.rebase_branch_onto_main_and_merge.assert_not_called()
    ctx.git_service.delete_remote_branches.assert_not_called()
    ctx.git_service.delete_local_branches.assert_not_called()


def test_rebase_command_keeps_branch_when_advanced_setting_disabled(project_registry: ProjectRegistry):
    advanced_settings_store = Mock()
    advanced_settings_store.get.return_value.delete_rebased_branch_enabled = False
    ctx = _ctx(project_registry, advanced_settings_store=advanced_settings_store)
    ctx.git_service.rebase_branch_onto_main_and_merge.return_value = "ok"
    ctx.git_service.list_remote_branches_matching.return_value = ["my-feature"]
    registry = CommandRegistry([RebaseCommand()])

    text = registry.dispatch(TelegramMessage(chat_id=1, user_id=1, text="/rebase my-feature"), ctx)

    assert text == "ok"
    ctx.git_service.delete_remote_branches.assert_not_called()
    ctx.git_service.delete_local_branches.assert_not_called()


def test_rebase_command_no_recent_branch(project_registry: ProjectRegistry):
    ctx = _ctx(project_registry)
    registry = CommandRegistry([RebaseCommand()])
    text = registry.dispatch(TelegramMessage(chat_id=42, user_id=1, text="/rebase"), ctx)
    assert "리베이스할 브랜치가 없습니다" in (text or "")
    ctx.git_service.rebase_branch_onto_main_and_merge.assert_not_called()


def test_rebase_command_lists_non_main_branch_buttons(project_registry: ProjectRegistry):
    ctx = _ctx(project_registry)
    ctx.git_service.resolve_integrate_branch.return_value = "main"
    ctx.git_service.list_local_branches.return_value = ["feature-a", "main", "release"]
    ctx.git_service.list_remote_branches_matching.return_value = ["feature-a", "main"]
    registry = CommandRegistry([RebaseCommand()])

    response = registry.dispatch_rich(TelegramMessage(chat_id=42, user_id=1, text="/rebase"), ctx)

    assert response is not None
    assert response.text == "리베이스할 브랜치를 선택하세요."
    assert response.inline_buttons == [
        [InlineButton("feature-a", "/rebase feature-a")],
    ]


def test_clear_branch_command_requests_confirmation(project_registry: ProjectRegistry):
    ctx = _ctx(project_registry)
    registry = CommandRegistry([ClearCommand()])
    text = registry.dispatch(TelegramMessage(chat_id=1, user_id=1, text="/clear branch"), ctx)
    assert "현재 할 작업" in (text or "")
    assert "remote-*" in (text or "")
    ctx.git_service.delete_remote_branches.assert_not_called()
    ctx.git_service.delete_local_branches.assert_not_called()


def test_clear_branch_command_uses_confirmation_buttons_when_enabled(project_registry: ProjectRegistry):
    advanced_settings_store = Mock()
    advanced_settings_store.get.return_value = AdvancedSettings(
        natural_job_confirmation_buttons_enabled=True,
    )
    ctx = _ctx(project_registry, advanced_settings_store=advanced_settings_store)
    registry = CommandRegistry([ClearCommand()])

    response = registry.dispatch_rich(TelegramMessage(chat_id=1, user_id=1, text="/clear branch"), ctx)

    assert response is not None
    assert "현재 할 작업" in response.text
    assert "실행 여부를 선택하세요." in response.text
    assert "y 또는 `Y`" not in response.text
    assert response.inline_buttons == [[InlineButton("네", "Y"), InlineButton("아니오", "n")]]
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


def test_clear_branch_only_targets_bot_bound_project(project_registry: ProjectRegistry, tmp_path: Path):
    root_b = tmp_path / "proj_b_root"
    root_b.mkdir()
    wt_b = tmp_path / "proj_b_wt"
    wt_b.mkdir()
    project_registry.add_project(
        ProjectRecord(
            name="proj-b",
            root_path=root_b,
            worktree_base_dir=wt_b,
            default_model=ModelName.CLAUDE,
            enabled=True,
            bot_token="456:b",
            allowed_chat_ids=[1],
        )
    )
    ctx = _ctx(project_registry)
    ctx.git_service.list_remote_branches_matching.return_value = []
    ctx.git_service.list_local_branches_matching.return_value = []
    registry = CommandRegistry([ClearCommand()])
    registry.dispatch(TelegramMessage(chat_id=1, user_id=1, text="/clear branch"), ctx)
    registry.dispatch(TelegramMessage(chat_id=1, user_id=1, text="y"), ctx)

    ctx.git_service.checkout_integrate_branch.assert_called_once()
    called_root = ctx.git_service.checkout_integrate_branch.call_args[0][0]
    assert called_root == project_registry.get("remote-coder").root_path
    assert called_root != root_b


def test_clear_worktrees_only_targets_bot_bound_project(project_registry: ProjectRegistry, tmp_path: Path):
    root_b = tmp_path / "proj_b_root2"
    root_b.mkdir()
    wt_b = tmp_path / "proj_b_wt2"
    wt_b.mkdir()
    project_registry.add_project(
        ProjectRecord(
            name="proj-b",
            root_path=root_b,
            worktree_base_dir=wt_b,
            default_model=ModelName.CLAUDE,
            enabled=True,
            bot_token="789:b",
            allowed_chat_ids=[1],
        )
    )
    ctx = _ctx(project_registry)
    ctx.git_service.cleanup_managed_worktrees.return_value = 0
    registry = CommandRegistry([ClearCommand()])
    registry.dispatch(TelegramMessage(chat_id=1, user_id=1, text="/clear worktrees"), ctx)
    registry.dispatch(TelegramMessage(chat_id=1, user_id=1, text="y"), ctx)

    ctx.git_service.cleanup_managed_worktrees.assert_called_once()
    args = ctx.git_service.cleanup_managed_worktrees.call_args[0]
    assert args[0] == project_registry.get("remote-coder").root_path
    assert args[1] == project_registry.get("remote-coder").worktree_base_dir


def test_clear_memory_only_deletes_current_project_and_chat(
    project_registry: ProjectRegistry, tmp_path: Path
):
    db = tmp_path / "clear_cmd_mem.sqlite3"
    conversation_store = SQLiteConversationStore(db)
    conversation_store.append(
        project="remote-coder", chat_id=1, role="user", text="keep-other-chat", job_id=None
    )
    conversation_store.append(
        project="remote-coder", chat_id=77, role="user", text="delete-me", job_id=None
    )
    conversation_store.append(
        project="other-proj", chat_id=77, role="user", text="keep-other-project", job_id=None
    )

    ctx = _ctx(project_registry, conversation_store=conversation_store)
    ctx.project_name = "remote-coder"
    registry = CommandRegistry([ClearCommand()])
    registry.dispatch(TelegramMessage(chat_id=77, user_id=1, text="/clear memory"), ctx)
    text = registry.dispatch(TelegramMessage(chat_id=77, user_id=1, text="y"), ctx)

    assert text is not None
    assert "대화 기억을 삭제했습니다" in text
    assert "project=remote-coder" in text
    assert len(conversation_store.list_recent("remote-coder", 1, 10)) == 1
    assert conversation_store.list_recent("remote-coder", 77, 10) == []
    assert len(conversation_store.list_recent("other-proj", 77, 10)) == 1


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
            bot_token="123:countproj",
            allowed_chat_ids=[123],
        )
    )
    project_registry.set_default_project("countproj")
    registry = CommandRegistry([MonitorCommand()])
    ctx = _ctx(project_registry)
    ctx.project_name = "countproj"
    text = registry.dispatch(TelegramMessage(chat_id=7, user_id=1, text="/monitor code"), ctx)
    assert text is not None
    assert "코드 규모" in text
    assert "스캔한 코드 파일 수: 1" in text


def test_help_command_get_inline_buttons_returns_none():
    cmd = HelpCommand()
    assert cmd.get_inline_buttons() is None


def test_dispatch_rich_help_has_no_buttons(project_registry: ProjectRegistry):
    registry = CommandRegistry([HelpCommand()])
    response = registry.dispatch_rich(
        TelegramMessage(chat_id=1, user_id=1, text="/help"),
        _ctx(project_registry),
    )
    assert response is not None
    assert response.text.startswith("도움말")
    assert response.inline_buttons is None


def test_dispatch_rich_non_help_has_no_buttons(project_registry: ProjectRegistry):
    registry = CommandRegistry([ModelCommand()])
    response = registry.dispatch_rich(
        TelegramMessage(chat_id=1, user_id=1, text="/model"),
        _ctx(project_registry),
    )
    assert response is not None
    assert response.inline_buttons is not None


def test_stop_command_lists_cancellable_jobs_as_buttons(project_registry: ProjectRegistry):
    registry = CommandRegistry([StopCommand()])
    response = registry.dispatch_rich(
        TelegramMessage(chat_id=1, user_id=1, text="/stop"),
        _ctx(project_registry),
    )

    assert response is not None
    assert response.text == "중단할 Job을 선택하세요."
    assert response.inline_buttons == [[InlineButton("job1 (queued)", "/stop job1")]]


def test_dispatch_rich_returns_none_for_natural_language(project_registry: ProjectRegistry):
    registry = CommandRegistry([ModelCommand()])
    response = registry.dispatch_rich(
        TelegramMessage(chat_id=1, user_id=1, text="자연어 메시지"),
        _ctx(project_registry),
    )
    assert response is None
