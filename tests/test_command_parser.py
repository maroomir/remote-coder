import pytest

from app.models import ModelName
from app.projects.registry import ProjectRecord, ProjectRegistry
from app.telegram.model_preferences import InMemoryModelPreferenceStore
from app.telegram.conversation import SQLiteConversationStore
from app.telegram.parser import CommandParseError, CommandParser


def test_parse_natural_returns_job_request(project_registry: ProjectRegistry):
    parser = CommandParser(project_registry=project_registry, default_model=ModelName.CLAUDE)
    req = parser.parse_natural("fix login bug", "remote-coder", chat_id=1, user_id=2)
    assert req.project == "remote-coder"
    assert req.model == ModelName.CLAUDE
    assert req.instruction == "fix login bug"


def test_parse_natural_raises_on_empty(project_registry: ProjectRegistry):
    parser = CommandParser(project_registry=project_registry, default_model=ModelName.CLAUDE)
    with pytest.raises(CommandParseError):
        parser.parse_natural("   ", "remote-coder", chat_id=1, user_id=2)


def test_parse_natural_uses_model_preference(project_registry: ProjectRegistry):
    pref = InMemoryModelPreferenceStore(default_model=ModelName.CLAUDE)
    pref.set(1, ModelName.CODEX)
    parser = CommandParser(
        project_registry=project_registry,
        default_model=ModelName.CLAUDE,
        model_preferences=pref,
    )
    req = parser.parse_natural("fix login bug", "remote-coder", chat_id=1, user_id=2)
    assert req.model == ModelName.CODEX


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
    with pytest.raises(CommandParseError, match="브랜치"):
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
    assert "[이전 대화/작업 맥락]" in req.instruction
    assert "작업 시작해줘" in req.instruction


def test_parse_natural_ambiguous_without_history_raises(project_registry: ProjectRegistry):
    db = project_registry.config_path.parent / "parser_empty.sqlite3"
    store = SQLiteConversationStore(db)
    parser = CommandParser(
        project_registry=project_registry,
        default_model=ModelName.CLAUDE,
        conversation_store=store,
    )
    with pytest.raises(CommandParseError, match="맥락"):
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
    assert "[Reply 체인 맥락]" in req.instruction
    assert "message_id=1" in req.instruction
    assert "message_id=2" in req.instruction
    assert "task A" in req.instruction
    assert "task B" in req.instruction
    assert "status=succeeded" in req.instruction
    assert "status=failed" in req.instruction
    assert "task C finish" in req.instruction


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
    assert "[Reply 체인 맥락]" in req.instruction
    assert "first instruction" in req.instruction
    assert "second instruction" in req.instruction
    assert "[이전 대화/작업 맥락]" in req.instruction
    body_after_reply = req.instruction.split("[/Reply 체인 맥락]", 1)[-1]
    assert "user: first instruction" not in body_after_reply
    assert "user: second instruction" not in body_after_reply


def test_parse_natural_rejects_unknown_project_name(project_registry: ProjectRegistry):
    parser = CommandParser(project_registry=project_registry, default_model=ModelName.CLAUDE)
    with pytest.raises(CommandParseError, match="알 수 없는 프로젝트"):
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
    with pytest.raises(CommandParseError, match="맥락"):
        parser.parse_natural("작업 시작해줘", "remote-coder", chat_id=99, user_id=1)
