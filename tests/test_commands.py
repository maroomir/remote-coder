from pathlib import Path
from threading import Event, Thread
from unittest.mock import Mock, patch

from app import __version__
from app.admin.advanced_settings import AdvancedSettings
from app.jobs.schemas import Job, JobRequest, JobStatus
from app.jobs.store import InMemoryJobStore
from app.models import ModelName, UiLanguage
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
    PrCommand,
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
from app.telegram.model_preferences import InMemoryModelPreferenceStore, ModelPreference


def _advanced_settings_ko() -> Mock:
    m = Mock()
    m.get.return_value = AdvancedSettings(ui_language=UiLanguage.KOREAN)
    return m


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
    text = registry.dispatch(
        TelegramMessage(chat_id=1, user_id=1, text="/help"),
        _ctx(project_registry, advanced_settings_store=_advanced_settings_ko()),
    )
    assert text is not None
    assert text.startswith("Help")
    assert "Send work requests as regular messages." in text
    assert "Options\n- model:\n- branch:\n- no commit" in text
    assert "/plan" in text and "/ask" in text
    assert "Commands:" in text
    assert "/clear branch:" not in text


def test_help_command_uses_english_when_advanced_language_default(project_registry: ProjectRegistry):
    advanced_settings_store = Mock()
    advanced_settings_store.get.return_value = AdvancedSettings()
    registry = CommandRegistry(build_default_commands())

    response = registry.dispatch_rich(
        TelegramMessage(chat_id=1, user_id=1, text="/help"),
        _ctx(project_registry, advanced_settings_store=advanced_settings_store),
    )

    assert response is not None
    from app.telegram.i18n import HELP_MAIN_EN

    assert response.text == HELP_MAIN_EN
    assert response.inline_buttons is not None
    assert response.inline_buttons[0][0].label == "model"


def test_dispatch_rich_help_body_skips_notifier_i18n_flag(project_registry: ProjectRegistry):
    registry = CommandRegistry(build_default_commands())
    ctx = _ctx(project_registry)
    main = registry.dispatch_rich(TelegramMessage(chat_id=1, user_id=1, text="/help"), ctx)
    assert main is not None and not main.skip_notifier_body_i18n
    agent = registry.dispatch_rich(TelegramMessage(chat_id=1, user_id=1, text="/help agent"), ctx)
    assert agent is not None and not agent.skip_notifier_body_i18n
    sub = registry.dispatch_rich(TelegramMessage(chat_id=1, user_id=1, text="/help model"), ctx)
    assert sub is not None and not sub.skip_notifier_body_i18n


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
        "fix",
        "plan",
        "ask",
    ]
    assert all("/" not in item["command"] for item in commands)
    assert all(item["description"] for item in commands)
    assert commands[0]["description"] == "Show the menu and project status"


def test_help_command_returns_text_with_no_buttons(project_registry: ProjectRegistry):
    registry = CommandRegistry([HelpCommand()])
    response = registry.dispatch_rich(
        TelegramMessage(chat_id=1, user_id=1, text="/help"),
        _ctx(project_registry, advanced_settings_store=_advanced_settings_ko()),
    )
    assert response is not None
    assert response.text.startswith("Help")
    assert response.inline_buttons is None


def test_start_shows_package_version(project_registry: ProjectRegistry):
    registry = CommandRegistry([StartCommand()])
    response = registry.dispatch_rich(TelegramMessage(chat_id=1, user_id=1, text="/start"), _ctx(project_registry))

    assert response is not None
    assert response.text.startswith(f"✅ Remote AI Coder v{__version__} is ready.")


def test_start_menu_places_model_under_manage(project_registry: ProjectRegistry):
    registry = CommandRegistry([StartCommand()])
    ctx = _ctx(project_registry)

    start_response = registry.dispatch_rich(TelegramMessage(chat_id=1, user_id=1, text="/start"), ctx)
    manage_response = registry.dispatch_rich(TelegramMessage(chat_id=1, user_id=1, text="/start manage"), ctx)

    assert start_response is not None
    assert start_response.inline_buttons == [
        [InlineButton("Help", "/help"), InlineButton("Modes", "/start modes")],
        [InlineButton("Monitor", "/monitor"), InlineButton("Clean", "/clear")],
        [InlineButton("Manage", "/start manage"), InlineButton("Reports", "/reports")],
    ]
    assert manage_response is not None
    assert manage_response.inline_buttons == [
        [InlineButton("Branch", "/branch"), InlineButton("Pull", "/pull")],
        [InlineButton("Rebase", "/rebase"), InlineButton("Open PR", "/pr")],
        [InlineButton("Stop", "/stop"), InlineButton("Status", "/status")],
        [InlineButton("Model", "/model"), InlineButton("Reset", "/init")],
        [InlineButton("Back", "/start")],
    ]


def test_start_modes_shows_mode_help_buttons(project_registry: ProjectRegistry):
    registry = CommandRegistry([StartCommand()])
    response = registry.dispatch_rich(TelegramMessage(chat_id=1, user_id=1, text="/start modes"), _ctx(project_registry))

    assert response is not None
    assert response.text == "Choose a mode guide."
    assert response.inline_buttons == [
        [
            InlineButton("AGENTS mode", "/help agent"),
            InlineButton("PLAN mode", "/help plan"),
            InlineButton("ASK mode", "/help ask"),
            InlineButton("FIX mode", "/help fix"),
        ],
        [InlineButton("Back", "/start")],
    ]


def test_start_model_topic_falls_back_to_main_menu(project_registry: ProjectRegistry):
    registry = CommandRegistry([StartCommand()])
    response = registry.dispatch_rich(TelegramMessage(chat_id=1, user_id=1, text="/start model"), _ctx(project_registry))

    assert response is not None
    assert response.text.startswith("✅ Remote AI Coder v")
    assert response.inline_buttons == [
        [InlineButton("Help", "/help"), InlineButton("Modes", "/start modes")],
        [InlineButton("Monitor", "/monitor"), InlineButton("Clean", "/clear")],
        [InlineButton("Manage", "/start manage"), InlineButton("Reports", "/reports")],
    ]


def test_dispatch_plan_and_ask_returns_none_for_natural_flow(project_registry: ProjectRegistry):
    registry = CommandRegistry(build_default_commands())
    ctx = _ctx(project_registry)
    assert registry.dispatch(TelegramMessage(chat_id=1, user_id=1, text="/plan outline only"), ctx) is None
    assert registry.dispatch(TelegramMessage(chat_id=1, user_id=1, text="/ask explain routing"), ctx) is None


def test_help_agent_plan_and_ask_topics(project_registry: ProjectRegistry):
    registry = CommandRegistry(build_default_commands())
    ctx = _ctx(project_registry, advanced_settings_store=_advanced_settings_ko())
    agent_text = registry.dispatch(TelegramMessage(chat_id=1, user_id=1, text="/help agent"), ctx)
    assert agent_text is not None
    assert "AGENTS mode" in agent_text
    assert "branch, commit, and push" in agent_text
    plan_text = registry.dispatch(TelegramMessage(chat_id=1, user_id=1, text="/help plan"), ctx)
    assert plan_text is not None
    assert "Plan mode" in plan_text
    assert "plan:" in plan_text
    assert "y" in plan_text or "Y" in plan_text
    ask_text = registry.dispatch(TelegramMessage(chat_id=1, user_id=1, text="/help ask"), ctx)
    assert ask_text is not None
    assert "Ask mode" in ask_text
    assert "/ask" in ask_text
    assert registry.dispatch(TelegramMessage(chat_id=1, user_id=1, text="/help 에이전트"), ctx) == agent_text
    assert registry.dispatch(TelegramMessage(chat_id=1, user_id=1, text="/help 계획"), ctx) == plan_text
    assert registry.dispatch(TelegramMessage(chat_id=1, user_id=1, text="/help 질문"), ctx) == ask_text


def test_help_plan_topic_shows_back_button(project_registry: ProjectRegistry):
    registry = CommandRegistry(build_default_commands())
    response = registry.dispatch_rich(
        TelegramMessage(chat_id=1, user_id=1, text="/help plan"),
        _ctx(project_registry),
    )
    assert response is not None
    assert response.inline_buttons == [[InlineButton("← Back", "/help")]]


def test_status_command_dispatch(project_registry: ProjectRegistry):
    registry = CommandRegistry([StatusCommand()])
    text = registry.dispatch(
        TelegramMessage(chat_id=1, user_id=1, text="/status job1"),
        _ctx(project_registry),
    )
    assert text is not None
    assert "job1" in text
    assert "queued" in text
    assert "Project:" in text
    assert "Model used:" in text


def test_status_command_lists_recent_jobs_as_buttons(project_registry: ProjectRegistry):
    registry = CommandRegistry([StatusCommand()])
    response = registry.dispatch_rich(
        TelegramMessage(chat_id=1, user_id=1, text="/status"),
        _ctx(project_registry),
    )

    assert response is not None
    assert response.text == "Choose a job to inspect."
    assert response.inline_buttons == [[InlineButton("job1 (queued)", "/status job1")]]


def test_model_command_updates_preference(project_registry: ProjectRegistry):
    registry = CommandRegistry([ModelCommand()])
    ctx = _ctx(project_registry)
    text = registry.dispatch(TelegramMessage(chat_id=77, user_id=1, text="/model codex"), ctx)
    assert text == "Model provider selected.\n\n- Default model: codex\n- Choose a specific model."
    current = registry.dispatch(TelegramMessage(chat_id=77, user_id=1, text="/model"), ctx)
    assert current == "Model settings\n\n- Current default model: codex"


def test_model_command_shows_model_buttons(project_registry: ProjectRegistry):
    registry = CommandRegistry([ModelCommand()])
    response = registry.dispatch_rich(TelegramMessage(chat_id=77, user_id=1, text="/model"), _ctx(project_registry))

    assert response is not None
    assert response.text == "Model settings\n\n- Current default model: claude"
    assert response.inline_buttons == [
        [
            InlineButton("claude", "/model claude"),
            InlineButton("codex", "/model codex"),
            InlineButton("gemini", "/model gemini"),
        ]
    ]


def test_model_command_shows_detail_buttons_after_provider_selection(project_registry: ProjectRegistry):
    registry = CommandRegistry([ModelCommand()])
    response = registry.dispatch_rich(
        TelegramMessage(chat_id=77, user_id=1, text="/model codex"),
        _ctx(project_registry),
    )

    assert response is not None
    assert response.text == "Model provider selected.\n\n- Default model: codex\n- Choose a specific model."
    assert response.inline_buttons is not None
    assert response.inline_buttons[0] == [InlineButton("gpt-5.3-codex", "/model codex gpt-5.3-codex")]


def test_model_command_confirms_detail_model(project_registry: ProjectRegistry):
    registry = CommandRegistry([ModelCommand()])
    ctx = _ctx(project_registry)

    response = registry.dispatch_rich(
        TelegramMessage(chat_id=77, user_id=1, text="/model codex gpt-5.3-codex"),
        ctx,
    )

    assert response is not None
    assert response.text == "Model setting updated.\n\n- Default model: codex / gpt-5.3-codex"
    assert response.inline_buttons is None
    assert ctx.model_preferences.get_explicit_selection(ctx.project_name, 77) == ModelPreference(
        ModelName.CODEX,
        "gpt-5.3-codex",
    )
    current = registry.dispatch(TelegramMessage(chat_id=77, user_id=1, text="/model"), ctx)
    assert current == "Model settings\n\n- Current default model: codex / gpt-5.3-codex"


def test_model_command_updates_preference_to_gemini(project_registry: ProjectRegistry):
    registry = CommandRegistry([ModelCommand()])
    ctx = _ctx(project_registry)
    text = registry.dispatch(TelegramMessage(chat_id=77, user_id=1, text="/model gemini"), ctx)
    assert text == "Model provider selected.\n\n- Default model: gemini\n- Choose a specific model."
    assert ctx.model_preferences.get(ctx.project_name, 77) == ModelName.GEMINI


def test_model_command_returns_consistent_usage(project_registry: ProjectRegistry):
    registry = CommandRegistry([ModelCommand()])
    text = registry.dispatch(TelegramMessage(chat_id=77, user_id=1, text="/model nope"), _ctx(project_registry))
    assert text == (
        "Usage\n\n"
        "- /model\n"
        "- /model <claude|codex|gemini>\n"
        "- /model <claude|codex|gemini> <model_id>"
    )


def test_model_command_rejects_invalid_detail_model(project_registry: ProjectRegistry):
    registry = CommandRegistry([ModelCommand()])
    text = registry.dispatch(
        TelegramMessage(chat_id=77, user_id=1, text="/model codex nope"),
        _ctx(project_registry),
    )
    assert text is not None
    assert "Unknown specific model: nope" in text


def test_monitor_project_lists_registry(project_registry: ProjectRegistry):
    registry = CommandRegistry([MonitorCommand()])
    text = registry.dispatch(TelegramMessage(chat_id=1, user_id=1, text="/monitor project"), _ctx(project_registry))
    assert text is not None
    assert "remote-coder" in text
    assert "This bot project" in text


def test_init_command_resets_project_model_and_pending(project_registry: ProjectRegistry):
    root = project_registry.config_path.parent / "init_other_repo"
    root.mkdir()
    project_registry.add_project(
        ProjectRecord(
            name="other",
            root_path=root,
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
    assert "were reset" in text
    assert "Project: other" in text
    assert "Default model: codex" in text
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
    assert text is not None and "were reset" in text
    assert ctx.confirmation_store.get(pname, chat_id) is None


def test_init_command_rejects_extra_args(project_registry: ProjectRegistry):
    registry = CommandRegistry([InitCommand()])
    text = registry.dispatch(
        TelegramMessage(chat_id=1, user_id=1, text="/init extra"),
        _ctx(project_registry),
    )
    assert text == "Usage\n\n- /init"


def test_branch_command_shows_current_branch(project_registry: ProjectRegistry):
    ctx = _ctx(project_registry)
    ctx.git_service.get_current_branch.return_value = "main"
    registry = CommandRegistry([BranchCommand()])
    text = registry.dispatch(TelegramMessage(chat_id=5, user_id=1, text="/branch"), ctx)
    assert "Current branch" in text
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
    assert "selected" in text
    ctx.git_service.local_branch_exists.assert_called_once()
    ctx.git_service.switch_branch.assert_called_once()


def test_branch_command_missing_branch_error(project_registry: ProjectRegistry):
    ctx = _ctx(project_registry)
    ctx.git_service.local_branch_exists.return_value = False
    registry = CommandRegistry([BranchCommand()])
    text = registry.dispatch(TelegramMessage(chat_id=5, user_id=1, text="/branch nope"), ctx)
    assert "not found" in text
    ctx.git_service.switch_branch.assert_not_called()


def test_branch_command_rejects_invalid_token(project_registry: ProjectRegistry):
    ctx = _ctx(project_registry)
    registry = CommandRegistry([BranchCommand()])
    text = registry.dispatch(TelegramMessage(chat_id=5, user_id=1, text="/branch bad name"), ctx)
    assert text == "Usage\n\n- /branch\n- /branch <branch>"


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

    assert text == "rebase ok\nDeleted branch `remote-abc` locally and from `origin`."
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
    assert text == "ok\nDeleted branch `my-feature` locally and from `origin`."
    assert ctx.git_service.rebase_branch_onto_main_and_merge.call_args[0][1] == "my-feature"
    ctx.git_service.delete_remote_branches.assert_called_once()
    ctx.git_service.delete_local_branches.assert_called_once()


def test_rebase_command_rejects_duplicate_inflight_branch(project_registry: ProjectRegistry):
    ctx = _ctx(project_registry)
    ctx.git_service.list_remote_branches_matching.return_value = ["my-feature"]
    first_started = Event()
    release_first = Event()

    def _rebase(*_args):
        first_started.set()
        assert release_first.wait(timeout=2)
        return "ok"

    ctx.git_service.rebase_branch_onto_main_and_merge.side_effect = _rebase
    registry = CommandRegistry([RebaseCommand()])
    first_text: list[str | None] = []

    def _run_first() -> None:
        first_text.append(registry.dispatch(TelegramMessage(chat_id=1, user_id=1, text="/rebase my-feature"), ctx))

    thread = Thread(target=_run_first)
    thread.start()
    assert first_started.wait(timeout=2)

    second_text = registry.dispatch(TelegramMessage(chat_id=1, user_id=1, text="/rebase my-feature"), ctx)

    release_first.set()
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert "already running" in (second_text or "")
    assert first_text == ["ok\nDeleted branch `my-feature` locally and from `origin`."]
    ctx.git_service.rebase_branch_onto_main_and_merge.assert_called_once()
    ctx.git_service.delete_remote_branches.assert_called_once()
    ctx.git_service.delete_local_branches.assert_called_once()


def test_rebase_command_reports_missing_remote_branch(project_registry: ProjectRegistry):
    ctx = _ctx(project_registry)
    ctx.git_service.list_remote_branches_matching.return_value = ["other-feature"]
    registry = CommandRegistry([RebaseCommand()])

    text = registry.dispatch(TelegramMessage(chat_id=1, user_id=1, text="/rebase stale-feature"), ctx)

    assert "`stale-feature` remote branch" in (text or "")
    assert "already been rebased/merged and deleted" in (text or "")
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
    assert "No branch is available to rebase" in (text or "")
    ctx.git_service.rebase_branch_onto_main_and_merge.assert_not_called()


def test_rebase_command_lists_non_main_branch_buttons(project_registry: ProjectRegistry):
    ctx = _ctx(project_registry)
    ctx.git_service.resolve_integrate_branch.return_value = "main"
    ctx.git_service.list_local_branches.return_value = ["feature-a", "main", "release"]
    ctx.git_service.list_remote_branches_matching.return_value = ["feature-a", "main"]
    registry = CommandRegistry([RebaseCommand()])

    response = registry.dispatch_rich(TelegramMessage(chat_id=42, user_id=1, text="/rebase"), ctx)

    assert response is not None
    assert response.text == "Choose a branch to rebase."
    assert response.inline_buttons == [
        [InlineButton("feature-a", "/rebase feature-a")],
    ]


def test_pr_command_rejects_non_ascii_branch(project_registry: ProjectRegistry):
    ctx = _ctx(project_registry)
    registry = CommandRegistry([PrCommand()])

    text = registry.dispatch(TelegramMessage(chat_id=42, user_id=1, text="/pr 기능/수정"), ctx)

    assert text == "Branch names may only use letters, numbers, /, ., _, and -."
    ctx.git_service.create_github_pr.assert_not_called()


def test_pr_content_uses_ascii_fallback_for_non_ascii_conversation(project_registry: ProjectRegistry):
    ctx = _ctx(project_registry)
    ctx.conversation_store = Mock()
    ctx.conversation_store.get_entries_for_branch.return_value = [
        ("로그인 검증 수정해줘", "수정 완료"),
    ]

    title, body = PrCommand()._build_pr_content("remote-fix-login-20260606-010203", "remote-coder", 42, ctx)

    assert title == "fix login"
    assert "로그인" not in body
    assert "수정 완료" not in body
    assert "Work branch: `remote-fix-login-20260606-010203`" in body
    assert "Request omitted because it contains non-ASCII text." in body
    assert "AI result omitted because it contains non-ASCII text." in body


def test_clear_branch_command_requests_confirmation(project_registry: ProjectRegistry):
    ctx = _ctx(project_registry)
    registry = CommandRegistry([ClearCommand()])
    text = registry.dispatch(TelegramMessage(chat_id=1, user_id=1, text="/clear branch"), ctx)
    assert "Pending action" in (text or "")
    assert "remote-*" in (text or "")
    ctx.git_service.delete_remote_branches.assert_not_called()
    ctx.git_service.delete_local_branches.assert_not_called()


def test_clear_branch_command_uses_confirmation_buttons_when_enabled(project_registry: ProjectRegistry):
    advanced_settings_store = Mock()
    advanced_settings_store.get.return_value = AdvancedSettings(
        ui_language="ko",
        natural_job_confirmation_buttons_enabled=True,
    )
    ctx = _ctx(project_registry, advanced_settings_store=advanced_settings_store)
    registry = CommandRegistry([ClearCommand()])

    response = registry.dispatch_rich(TelegramMessage(chat_id=1, user_id=1, text="/clear branch"), ctx)

    assert response is not None
    assert "Pending action" in response.text
    assert "Choose whether to run it." in response.text
    assert "y 또는 `Y`" not in response.text
    assert response.inline_buttons == [[InlineButton("Yes", "Y"), InlineButton("No", "n")]]
    ctx.git_service.delete_remote_branches.assert_not_called()
    ctx.git_service.delete_local_branches.assert_not_called()


def test_clear_command_lists_cleanup_options_as_buttons(project_registry: ProjectRegistry):
    ctx = _ctx(project_registry)
    registry = CommandRegistry([ClearCommand()])

    response = registry.dispatch_rich(TelegramMessage(chat_id=1, user_id=1, text="/clear"), ctx)

    assert response is not None
    assert response.text == "Choose what to clear. Confirmation with y/Y is required before running."
    assert response.inline_buttons == [
        [
            InlineButton("branch", "/clear branch"),
            InlineButton("worktrees", "/clear worktrees"),
            InlineButton("memory", "/clear memory"),
        ],
    ]


def test_clear_worktrees_command_requests_confirmation(project_registry: ProjectRegistry):
    ctx = _ctx(project_registry)
    registry = CommandRegistry([ClearCommand()])
    text = registry.dispatch(TelegramMessage(chat_id=1, user_id=1, text="/clear worktrees"), ctx)
    assert "Pending action" in (text or "")
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
    assert "remote 1" in (text or "")
    assert "local 1" in (text or "")
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
    assert "2 worktrees deleted" in (text or "")
    assert "stale entries pruned" in (text or "")
    ctx.git_service.cleanup_managed_worktrees.assert_called_once()


def test_clear_branch_only_targets_bot_bound_project(project_registry: ProjectRegistry, tmp_path: Path):
    root_b = tmp_path / "proj_b_root"
    root_b.mkdir()
    project_registry.add_project(
        ProjectRecord(
            name="proj-b",
            root_path=root_b,
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
    project_registry.add_project(
        ProjectRecord(
            name="proj-b",
            root_path=root_b,
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
    assert "Deleted this chat's conversation memory" in text
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
    assert "Memory report" in text
    assert "Total entries: 2" in text
    assert "Latest user request: README 수정해줘" in text
    assert "job-7" in text


def test_reports_command_handles_empty_memory(project_registry: ProjectRegistry, tmp_path):
    db = tmp_path / "cmd_reports_empty.sqlite3"
    ctx = _ctx(project_registry)
    ctx.conversation_store = SQLiteConversationStore(db)
    registry = CommandRegistry([ReportsCommand()])

    text = registry.dispatch(TelegramMessage(chat_id=77, user_id=1, text="/reports"), ctx)

    assert text == "No conversation memory is stored. (project=remote-coder)"


def test_monitor_command_shows_usage(project_registry: ProjectRegistry):
    registry = CommandRegistry([MonitorCommand()])
    response = registry.dispatch_rich(
        TelegramMessage(chat_id=1, user_id=1, text="/monitor"),
        _ctx(project_registry),
    )

    assert response is not None
    assert response.text == "Choose a monitoring view."
    assert response.inline_buttons == [
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
    ]


def test_monitor_command_rejects_invalid_subcommand(project_registry: ProjectRegistry):
    registry = CommandRegistry([MonitorCommand()])
    text = registry.dispatch(
        TelegramMessage(chat_id=1, user_id=1, text="/monitor nope"),
        _ctx(project_registry),
    )
    assert text is not None
    assert "Usage" in text


def test_monitor_memory_shows_sqlite_stats(project_registry: ProjectRegistry, tmp_path):
    db = tmp_path / "monitor_mem.sqlite3"
    store = SQLiteConversationStore(db)
    store.append(project="remote-coder", chat_id=42, role="user", text="hi", job_id=None)
    ctx = _ctx(project_registry)
    ctx.conversation_store = store
    registry = CommandRegistry([MonitorCommand()])
    text = registry.dispatch(TelegramMessage(chat_id=42, user_id=1, text="/monitor memory"), ctx)
    assert text is not None
    assert "Memory (SQLite)" in text
    assert "Rows for this chat: 1" in text
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
    assert "Branch monitor" in text
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
    assert "Worktree monitor" in text
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
    assert "Current chat default model: claude" in text
    assert "[Claude]" in text
    assert "Observed detailed model: Claude Opus 4.7" in text
    assert "input=100" in text


def test_monitor_code_counts_lines(project_registry: ProjectRegistry, tmp_path):
    root = project_registry.config_path.parent / "count_repo"
    root.mkdir(parents=True)
    (root / "a.py").write_text("# x\nprint(1)\n", encoding="utf-8")
    project_registry.add_project(
        ProjectRecord(
            name="countproj",
            root_path=root,
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
    assert "Code size" in text
    assert "Code files scanned: 1" in text


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
    assert response.text.startswith("Help")
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
    assert response.text == "Choose a job to stop."
    assert response.inline_buttons == [[InlineButton("job1 (queued)", "/stop job1")]]


def test_dispatch_rich_returns_none_for_natural_language(project_registry: ProjectRegistry):
    registry = CommandRegistry([ModelCommand()])
    response = registry.dispatch_rich(
        TelegramMessage(chat_id=1, user_id=1, text="자연어 메시지"),
        _ctx(project_registry),
    )
    assert response is None


# ---- /fix tests -----------------------------------------------------------


def test_registry_dispatch_returns_none_for_bare_fix(project_registry: ProjectRegistry):
    from app.telegram.commands import FixCommand

    registry = CommandRegistry([FixCommand()])
    assert registry.dispatch(TelegramMessage(chat_id=1, user_id=1, text="/fix"), _ctx(project_registry)) is None


def test_fix_command_execute_describes_reply_requirement(project_registry: ProjectRegistry):
    from app.telegram.commands import FixCommand

    cmd = FixCommand()
    text = cmd.execute(TelegramMessage(chat_id=1, user_id=1, text="/fix"), _ctx(project_registry))
    assert "replying to a job result" in text
