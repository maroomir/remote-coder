from unittest.mock import Mock

import pytest

from app.admin.advanced_settings import AdvancedSettings
from app.jobs.schemas import JobMode
from app.models import ModelName, UiLanguage
from app.projects.registry import ProjectRecord, ProjectRegistry
from app.telegram.conversation import SQLiteConversationStore
from app.telegram.model_preferences import InMemoryModelPreferenceStore
from app.telegram.parser import CommandParseError, CommandParser


def test_parse_natural_returns_job_request(project_registry: ProjectRegistry):
    parser = CommandParser(project_registry=project_registry, default_model=ModelName.CLAUDE)
    req = parser.parse_natural("fix login bug", "remote-coder", chat_id=1, user_id=2)
    assert req.project == "remote-coder"
    assert req.model == ModelName.CLAUDE
    assert req.instruction == "fix login bug"


def test_parse_natural_uses_korean_instruction_frames_when_advanced_settings_ko(
    project_registry: ProjectRegistry,
):
    store_mock = Mock()
    store_mock.get.return_value = AdvancedSettings(ui_language=UiLanguage.KOREAN)
    db = project_registry.config_path.parent / "parser_ko_frames.sqlite3"
    conv = SQLiteConversationStore(db)
    conv.append(project="remote-coder", chat_id=9, role="user", text="한글 맥락", job_id=None)
    parser = CommandParser(
        project_registry=project_registry,
        default_model=ModelName.CLAUDE,
        conversation_store=conv,
        advanced_settings_store=store_mock,
    )
    req = parser.parse_natural("작업 시작해줘", "remote-coder", chat_id=9, user_id=1)
    assert "[이전 대화/작업 맥락]" in req.instruction


def test_parse_natural_raises_on_empty(project_registry: ProjectRegistry):
    parser = CommandParser(project_registry=project_registry, default_model=ModelName.CLAUDE)
    with pytest.raises(CommandParseError):
        parser.parse_natural("   ", "remote-coder", chat_id=1, user_id=2)


def test_parse_natural_uses_model_preference(project_registry: ProjectRegistry):
    pref = InMemoryModelPreferenceStore(default_model=ModelName.CLAUDE)
    pref.set("remote-coder", 1, ModelName.CODEX)
    parser = CommandParser(
        project_registry=project_registry,
        default_model=ModelName.CLAUDE,
        model_preferences=pref,
    )
    req = parser.parse_natural("fix login bug", "remote-coder", chat_id=1, user_id=2)
    assert req.model == ModelName.CODEX


def test_parse_natural_model_preference_scoped_by_project_same_chat_id(project_registry: ProjectRegistry):
    root = project_registry.config_path.parent / "scoped_pref_repo"
    root.mkdir()
    wt = project_registry.config_path.parent / "scoped_pref_wt"
    wt.mkdir()
    project_registry.add_project(
        ProjectRecord(
            name="scoped-pref-proj",
            root_path=root,
            worktree_base_dir=wt,
            default_model=ModelName.GEMINI,
            enabled=True,
            bot_token="123:scoped_pref",
            allowed_chat_ids=[123],
        )
    )
    pref = InMemoryModelPreferenceStore(default_model=ModelName.CLAUDE)
    pref.set("remote-coder", 42, ModelName.CODEX)
    parser = CommandParser(
        project_registry=project_registry,
        default_model=ModelName.CLAUDE,
        model_preferences=pref,
    )
    req = parser.parse_natural("task", "scoped-pref-proj", chat_id=42, user_id=2)
    assert req.model == ModelName.GEMINI


def test_parse_natural_parses_model_branch_and_no_commit(project_registry: ProjectRegistry):
    parser = CommandParser(project_registry=project_registry, default_model=ModelName.CLAUDE)
    req = parser.parse_natural(
        "model: codex branch: remote/test no commit fix login bug",
        "remote-coder",
        chat_id=1,
        user_id=2,
    )
    assert req.model == ModelName.CODEX
    assert req.branch == "remote/test"
    assert not req.commit
    assert req.instruction == "fix login bug"


def test_parse_natural_parses_gemini_model(project_registry: ProjectRegistry):
    parser = CommandParser(project_registry=project_registry, default_model=ModelName.CLAUDE)
    req = parser.parse_natural("model: gemini fix login bug", "remote-coder", chat_id=1, user_id=2)
    assert req.model == ModelName.GEMINI
    assert req.instruction == "fix login bug"


def test_parse_natural_no_model_preferences_uses_project_default(project_registry: ProjectRegistry):
    root = project_registry.config_path.parent / "codex_only_repo"
    root.mkdir()
    wt = project_registry.config_path.parent / "codex_only_wt"
    wt.mkdir()
    project_registry.add_project(
        ProjectRecord(
            name="special",
            root_path=root,
            worktree_base_dir=wt,
            default_model=ModelName.CODEX,
            enabled=True,
            bot_token="123:special",
            allowed_chat_ids=[123],
        )
    )
    parser = CommandParser(
        project_registry=project_registry,
        default_model=ModelName.CLAUDE,
        model_preferences=None,
    )
    req = parser.parse_natural("task", "special", chat_id=1, user_id=2)
    assert req.model == ModelName.CODEX


def test_parse_natural_without_explicit_model_preference_uses_project_default(
    project_registry: ProjectRegistry,
):
    root = project_registry.config_path.parent / "project_default_repo"
    root.mkdir()
    wt = project_registry.config_path.parent / "project_default_wt"
    wt.mkdir()
    project_registry.add_project(
        ProjectRecord(
            name="project_default",
            root_path=root,
            worktree_base_dir=wt,
            default_model=ModelName.CODEX,
            enabled=True,
            bot_token="123:project_default",
            allowed_chat_ids=[123],
        )
    )
    parser = CommandParser(
        project_registry=project_registry,
        default_model=ModelName.CLAUDE,
        model_preferences=InMemoryModelPreferenceStore(default_model=ModelName.CLAUDE),
    )

    req = parser.parse_natural("task", "project_default", chat_id=1, user_id=2)

    assert req.model == ModelName.CODEX


def test_parse_natural_rejects_invalid_branch_token(project_registry: ProjectRegistry):
    parser = CommandParser(project_registry=project_registry, default_model=ModelName.CLAUDE)
    with pytest.raises(CommandParseError, match="Branch name"):
        parser.parse_natural("branch: bad..name fix bug", "remote-coder", chat_id=1, user_id=2)


def test_parse_natural_ambiguous_followup_merges_conversation(project_registry: ProjectRegistry):
    db = project_registry.config_path.parent / "parser_conv.sqlite3"
    store = SQLiteConversationStore(db)
    store.append(
        project="remote-coder",
        chat_id=99,
        role="user",
        text="README에 테스트 문구 한 줄 추가해줘",
        job_id=None,
    )
    parser = CommandParser(
        project_registry=project_registry,
        default_model=ModelName.CLAUDE,
        conversation_store=store,
        conversation_recent_limit=10,
    )
    req = parser.parse_natural("작업 시작해줘", "remote-coder", chat_id=99, user_id=1)
    assert "README" in req.instruction
    assert "[Previous conversation/job context]" in req.instruction
    assert "작업 시작해줘" in req.instruction


def test_parse_natural_ambiguous_without_history_raises(project_registry: ProjectRegistry):
    db = project_registry.config_path.parent / "parser_empty.sqlite3"
    store = SQLiteConversationStore(db)
    parser = CommandParser(
        project_registry=project_registry,
        default_model=ModelName.CLAUDE,
        conversation_store=store,
    )
    with pytest.raises(CommandParseError, match="previous job context"):
        parser.parse_natural("작업 시작해줘", "remote-coder", chat_id=42, user_id=1)


def test_parse_natural_reply_reuses_bound_branch(project_registry: ProjectRegistry):
    db = project_registry.config_path.parent / "parser_reply.sqlite3"
    store = SQLiteConversationStore(db)
    store.bind_message_branch(
        project="remote-coder",
        chat_id=99,
        message_id=11,
        branch="remote-a",
        job_id="job-1",
    )
    parser = CommandParser(
        project_registry=project_registry,
        default_model=ModelName.CLAUDE,
        conversation_store=store,
    )

    req = parser.parse_natural(
        "추가 기능도 반영해줘",
        "remote-coder",
        chat_id=99,
        user_id=1,
        message_id=12,
        reply_to_message_id=11,
    )

    assert req.branch == "remote-a"
    assert req.message_id == 12
    assert req.reply_to_message_id == 11


def test_parse_natural_reply_chain_includes_ancestors_and_job_results(project_registry: ProjectRegistry):
    db = project_registry.config_path.parent / "parser_reply_chain.sqlite3"
    store = SQLiteConversationStore(db)
    store.append(
        project="remote-coder",
        chat_id=5,
        role="user",
        text="task A",
        message_id=1,
        reply_to_message_id=None,
    )
    store.bind_message_branch(
        project="remote-coder",
        chat_id=5,
        message_id=1,
        branch="remote-x",
        job_id="j1",
    )
    store.append(
        project="remote-coder",
        chat_id=5,
        role="job_result",
        text="status=succeeded",
        job_id="j1",
    )
    store.append(
        project="remote-coder",
        chat_id=5,
        role="user",
        text="task B",
        message_id=2,
        reply_to_message_id=1,
    )
    store.bind_message_branch(
        project="remote-coder",
        chat_id=5,
        message_id=2,
        branch="remote-y",
        job_id="j2",
    )
    store.append(
        project="remote-coder",
        chat_id=5,
        role="job_result",
        text="status=failed stage=runner",
        job_id="j2",
    )
    parser = CommandParser(
        project_registry=project_registry,
        default_model=ModelName.CLAUDE,
        conversation_store=store,
    )
    req = parser.parse_natural(
        "task C finish",
        "remote-coder",
        chat_id=5,
        user_id=1,
        message_id=3,
        reply_to_message_id=2,
    )
    assert "[Reply chain context]" in req.instruction
    assert "message_id=1" in req.instruction
    assert "message_id=2" in req.instruction
    assert "task A" in req.instruction
    assert "task B" in req.instruction
    assert "status=succeeded" in req.instruction
    assert "status=failed" in req.instruction
    assert "task C finish" in req.instruction


def test_parse_natural_reply_includes_unstored_reply_text(project_registry: ProjectRegistry):
    db = project_registry.config_path.parent / "parser_reply_text.sqlite3"
    store = SQLiteConversationStore(db)
    parser = CommandParser(
        project_registry=project_registry,
        default_model=ModelName.CLAUDE,
        conversation_store=store,
    )

    req = parser.parse_natural(
        "이 응답 기준으로 이어서 수정해줘",
        "remote-coder",
        chat_id=5,
        user_id=1,
        message_id=31,
        reply_to_message_id=30,
        reply_to_text="작업 완료\nJob ID: job_1\nAI 응답:\nREADME를 수정했습니다.",
    )

    assert "[Reply message context]" in req.instruction
    assert "message_id=30" in req.instruction
    assert "README를 수정했습니다." in req.instruction
    assert "이 응답 기준으로 이어서 수정해줘" in req.instruction


def test_parse_natural_reply_to_bot_job_result_expands_job_context(project_registry: ProjectRegistry):
    db = project_registry.config_path.parent / "parser_reply_job_context.sqlite3"
    store = SQLiteConversationStore(db)
    store.append(
        project="remote-coder",
        chat_id=5,
        role="user",
        text="plan: 최초 plan 요청",
        job_id="job_20260513022227_2b174e",
        message_id=100,
    )
    store.append(
        project="remote-coder",
        chat_id=5,
        role="job_result",
        text="status=succeeded stdout_preview=계획 결과 요약",
        job_id="job_20260513022227_2b174e",
    )
    parser = CommandParser(
        project_registry=project_registry,
        default_model=ModelName.CLAUDE,
        conversation_store=store,
    )

    req = parser.parse_natural(
        "특성만 제거합니다. 진행해주세요",
        "remote-coder",
        chat_id=5,
        user_id=1,
        message_id=102,
        reply_to_message_id=101,
        reply_to_text="[plan] 응답 완료\n\n- Job ID: job_20260513022227_2b174e\nAI 응답:\n원본 일부",
    )

    assert "[Reply job context]" in req.instruction
    assert "최초 plan 요청" in req.instruction
    assert "계획 결과 요약" in req.instruction
    assert "특성만 제거합니다" in req.instruction
    assert "[Reply message context]" not in req.instruction


def test_parse_natural_reply_to_recorded_bot_message_reuses_job_id(project_registry: ProjectRegistry):
    db = project_registry.config_path.parent / "parser_reply_recorded_bot.sqlite3"
    store = SQLiteConversationStore(db)
    store.append(
        project="remote-coder",
        chat_id=5,
        role="user",
        text="plan: 최초 요청",
        job_id="job_same",
        message_id=100,
    )
    store.append(
        project="remote-coder",
        chat_id=5,
        role="job_result",
        text="status=succeeded stdout_preview=앱 응답",
        job_id="job_same",
        message_id=101,
    )
    parser = CommandParser(
        project_registry=project_registry,
        default_model=ModelName.CLAUDE,
        conversation_store=store,
    )

    req = parser.parse_natural(
        "이 응답 기준으로 이어서 수정해줘",
        "remote-coder",
        chat_id=5,
        user_id=1,
        message_id=102,
        reply_to_message_id=101,
    )

    assert req.job_id == "job_same"
    assert "최초 요청" in req.instruction
    assert "앱 응답" in req.instruction
    assert "이 응답 기준으로 이어서 수정해줘" in req.instruction


def test_parse_natural_ambiguous_reply_uses_unstored_reply_text(project_registry: ProjectRegistry):
    db = project_registry.config_path.parent / "parser_ambig_reply_text.sqlite3"
    store = SQLiteConversationStore(db)
    parser = CommandParser(
        project_registry=project_registry,
        default_model=ModelName.CLAUDE,
        conversation_store=store,
    )

    req = parser.parse_natural(
        "진행해줘",
        "remote-coder",
        chat_id=5,
        user_id=1,
        message_id=32,
        reply_to_message_id=30,
        reply_to_text="AI 응답:\nREADME를 수정했습니다.",
    )

    assert "[Reply message context]" in req.instruction
    assert "README를 수정했습니다." in req.instruction
    assert "진행해줘" in req.instruction


def test_parse_natural_ambiguous_on_reply_excludes_chain_from_recent_block(project_registry: ProjectRegistry):
    db = project_registry.config_path.parent / "parser_ambig_reply.sqlite3"
    store = SQLiteConversationStore(db)
    store.append(
        project="remote-coder",
        chat_id=8,
        role="user",
        text="first instruction",
        message_id=100,
        reply_to_message_id=None,
    )
    store.append(
        project="remote-coder",
        chat_id=8,
        role="job_accepted",
        text="Job 접수: jx",
        job_id="jx",
    )
    store.append(
        project="remote-coder",
        chat_id=8,
        role="job_result",
        text="status=succeeded",
        job_id="jx",
    )
    store.append(
        project="remote-coder",
        chat_id=8,
        role="user",
        text="second instruction",
        message_id=101,
        reply_to_message_id=100,
    )
    parser = CommandParser(
        project_registry=project_registry,
        default_model=ModelName.CLAUDE,
        conversation_store=store,
        conversation_recent_limit=10,
    )
    req = parser.parse_natural(
        "진행해줘",
        "remote-coder",
        chat_id=8,
        user_id=1,
        message_id=102,
        reply_to_message_id=101,
    )
    assert "[Reply chain context]" in req.instruction
    assert "first instruction" in req.instruction
    assert "second instruction" in req.instruction
    assert "[Previous conversation/job context]" in req.instruction
    body_after_reply = req.instruction.split("[/Reply chain context]", 1)[-1]
    assert "user: first instruction" not in body_after_reply
    assert "user: second instruction" not in body_after_reply


def test_parse_natural_rejects_unknown_project_name(project_registry: ProjectRegistry):
    parser = CommandParser(project_registry=project_registry, default_model=ModelName.CLAUDE)
    with pytest.raises(CommandParseError, match="Unknown project"):
        parser.parse_natural("do something", "no-such-project", chat_id=1, user_id=2)


def test_parse_natural_ambiguous_followup_reads_only_named_project_history(
    project_registry: ProjectRegistry,
):
    db = project_registry.config_path.parent / "parser_cross_project.sqlite3"
    store = SQLiteConversationStore(db)
    store.append(
        project="other-bot-project",
        chat_id=99,
        role="user",
        text="다른 봇 전용 비밀 맥락",
        job_id=None,
    )
    parser = CommandParser(
        project_registry=project_registry,
        default_model=ModelName.CLAUDE,
        conversation_store=store,
        conversation_recent_limit=10,
    )
    with pytest.raises(CommandParseError, match="previous job context"):
        parser.parse_natural("작업 시작해줘", "remote-coder", chat_id=99, user_id=1)


def test_parse_natural_plan_prefix_sets_mode(project_registry: ProjectRegistry):
    parser = CommandParser(project_registry=project_registry, default_model=ModelName.CLAUDE)
    req = parser.parse_natural("plan: refactor auth", "remote-coder", chat_id=1, user_id=2)
    assert req.mode == JobMode.PLAN
    assert req.instruction == "refactor auth"
    assert req.branch is None
    assert not req.commit


def test_parse_natural_plan_prefix_case_insensitive(project_registry: ProjectRegistry):
    parser = CommandParser(project_registry=project_registry, default_model=ModelName.CLAUDE)
    req = parser.parse_natural("PLAN: step one", "remote-coder", chat_id=1, user_id=2)
    assert req.mode == JobMode.PLAN
    assert req.instruction == "step one"


def test_parse_natural_ask_prefix_with_spaces_after_colon(project_registry: ProjectRegistry):
    parser = CommandParser(project_registry=project_registry, default_model=ModelName.CLAUDE)
    req = parser.parse_natural("ask:    explain modules", "remote-coder", chat_id=1, user_id=2)
    assert req.mode == JobMode.ASK
    assert req.instruction == "explain modules"


def test_parse_natural_plan_or_ask_empty_raises(project_registry: ProjectRegistry):
    parser = CommandParser(project_registry=project_registry, default_model=ModelName.CLAUDE)
    with pytest.raises(CommandParseError, match="empty"):
        parser.parse_natural("plan:", "remote-coder", chat_id=1, user_id=2)
    with pytest.raises(CommandParseError, match="empty"):
        parser.parse_natural("ask:   ", "remote-coder", chat_id=1, user_id=2)


def test_parse_natural_plan_with_model_option(project_registry: ProjectRegistry):
    parser = CommandParser(project_registry=project_registry, default_model=ModelName.CLAUDE)
    req = parser.parse_natural("plan: model: codex outline steps", "remote-coder", chat_id=1, user_id=2)
    assert req.mode == JobMode.PLAN
    assert req.model == ModelName.CODEX
    assert req.instruction == "outline steps"


def test_parse_natural_plan_ignores_branch_and_no_commit(project_registry: ProjectRegistry):
    parser = CommandParser(project_registry=project_registry, default_model=ModelName.CLAUDE)
    req = parser.parse_natural(
        "plan: branch: feature/foo no commit write tests",
        "remote-coder",
        chat_id=1,
        user_id=2,
    )
    assert req.mode == JobMode.PLAN
    assert req.branch is None
    assert not req.commit
    assert req.instruction == "write tests"


def test_parse_natural_plan_ignores_invalid_branch_token(project_registry: ProjectRegistry):
    parser = CommandParser(project_registry=project_registry, default_model=ModelName.CLAUDE)
    req = parser.parse_natural(
        "plan: branch: bad..name still parses",
        "remote-coder",
        chat_id=1,
        user_id=2,
    )
    assert req.mode == JobMode.PLAN
    assert req.branch is None
    assert req.instruction == "still parses"


def test_parse_natural_plan_skips_reply_bound_branch(project_registry: ProjectRegistry):
    db = project_registry.config_path.parent / "parser_plan_reply_branch.sqlite3"
    store = SQLiteConversationStore(db)
    store.bind_message_branch(
        project="remote-coder",
        chat_id=7,
        message_id=50,
        branch="feature/reply-branch",
        job_id="job-plan-skip",
    )
    parser = CommandParser(
        project_registry=project_registry,
        default_model=ModelName.CLAUDE,
        conversation_store=store,
    )
    req = parser.parse_natural(
        "plan: describe layout",
        "remote-coder",
        chat_id=7,
        user_id=1,
        message_id=51,
        reply_to_message_id=50,
    )
    assert req.mode == JobMode.PLAN
    assert req.branch is None


def test_parse_natural_default_mode_is_agent(project_registry: ProjectRegistry):
    parser = CommandParser(project_registry=project_registry, default_model=ModelName.CLAUDE)
    req = parser.parse_natural("fix login bug", "remote-coder", chat_id=1, user_id=2)
    assert req.mode == JobMode.AGENT


def test_parse_natural_slash_plan_and_ask(project_registry: ProjectRegistry):
    parser = CommandParser(project_registry=project_registry, default_model=ModelName.CLAUDE)
    req = parser.parse_natural("/PLAN  step one", "remote-coder", chat_id=1, user_id=2)
    assert req.mode == JobMode.PLAN
    assert req.instruction == "step one"
    req2 = parser.parse_natural("/ask   what is pytest?", "remote-coder", chat_id=1, user_id=2)
    assert req2.mode == JobMode.ASK
    assert "pytest" in req2.instruction


def test_parse_natural_fullwidth_colon_prefix(project_registry: ProjectRegistry):
    parser = CommandParser(project_registry=project_registry, default_model=ModelName.CLAUDE)
    req = parser.parse_natural("plan：전각 콜론 본문", "remote-coder", chat_id=1, user_id=2)
    assert req.mode == JobMode.PLAN
    assert "전각" in req.instruction


def test_parse_natural_korean_prefix_aliases(project_registry: ProjectRegistry):
    parser = CommandParser(project_registry=project_registry, default_model=ModelName.CLAUDE)
    req = parser.parse_natural("계획: 한글 접두", "remote-coder", chat_id=1, user_id=2)
    assert req.mode == JobMode.PLAN
    assert req.instruction == "한글 접두"
    req2 = parser.parse_natural("질문: 설명해줘", "remote-coder", chat_id=1, user_id=2)
    assert req2.mode == JobMode.ASK
    assert req2.instruction == "설명해줘"


def test_parse_natural_plan_empty_body_shows_examples(project_registry: ProjectRegistry):
    parser = CommandParser(project_registry=project_registry, default_model=ModelName.CLAUDE)
    with pytest.raises(CommandParseError, match="Example"):
        parser.parse_natural("plan:", "remote-coder", chat_id=1, user_id=2)
