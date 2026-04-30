import pytest

from app.models import ModelName
from app.projects.registry import ProjectRecord, ProjectRegistry
from app.telegram.model_preferences import InMemoryModelPreferenceStore
from app.telegram.conversation import SQLiteConversationStore
from app.telegram.parser import CommandParseError, CommandParser
from app.telegram.project_preferences import InMemoryProjectPreferenceStore


def test_parse_natural_returns_job_request(project_registry: ProjectRegistry):
    parser = CommandParser(project_registry=project_registry, default_model=ModelName.CLAUDE)
    req = parser.parse_natural("fix login bug", chat_id=1, user_id=2)
    assert req.project == "remote-coder"
    assert req.model == ModelName.CLAUDE
    assert req.instruction == "fix login bug"


def test_parse_natural_raises_on_empty(project_registry: ProjectRegistry):
    parser = CommandParser(project_registry=project_registry, default_model=ModelName.CLAUDE)
    with pytest.raises(CommandParseError):
        parser.parse_natural("   ", chat_id=1, user_id=2)


def test_parse_natural_uses_model_preference(project_registry: ProjectRegistry):
    pref = InMemoryModelPreferenceStore(default_model=ModelName.CLAUDE)
    pref.set(1, ModelName.CODEX)
    parser = CommandParser(
        project_registry=project_registry,
        default_model=ModelName.CLAUDE,
        model_preferences=pref,
    )
    req = parser.parse_natural("fix login bug", chat_id=1, user_id=2)
    assert req.model == ModelName.CODEX


def test_parse_natural_parses_model_branch_and_no_commit(project_registry: ProjectRegistry):
    parser = CommandParser(project_registry=project_registry, default_model=ModelName.CLAUDE)
    req = parser.parse_natural(
        "model: codex branch: remote/test no commit fix login bug",
        chat_id=1,
        user_id=2,
    )
    assert req.model == ModelName.CODEX
    assert req.branch == "remote/test"
    assert not req.commit
    assert req.instruction == "fix login bug"


def test_parse_natural_project_option(project_registry: ProjectRegistry):
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
    parser = CommandParser(project_registry=project_registry, default_model=ModelName.CLAUDE)
    req = parser.parse_natural("project: other do work", chat_id=1, user_id=2)
    assert req.project == "other"
    assert req.instruction == "do work"


def test_parse_natural_unknown_project(project_registry: ProjectRegistry):
    parser = CommandParser(project_registry=project_registry, default_model=ModelName.CLAUDE)
    with pytest.raises(CommandParseError, match="알 수 없는"):
        parser.parse_natural("project: nope fix", chat_id=1, user_id=2)


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
        )
    )
    parser = CommandParser(
        project_registry=project_registry,
        default_model=ModelName.CLAUDE,
        model_preferences=None,
    )
    req = parser.parse_natural("project: special task", chat_id=1, user_id=2)
    assert req.model == ModelName.CODEX


def test_parse_natural_uses_project_preference(project_registry: ProjectRegistry):
    root = project_registry.config_path.parent / "pref_repo"
    root.mkdir()
    wt = project_registry.config_path.parent / "pref_wt"
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
    pref = InMemoryProjectPreferenceStore()
    pref.set(7, "other")
    parser = CommandParser(
        project_registry=project_registry,
        default_model=ModelName.CLAUDE,
        project_preferences=pref,
    )
    req = parser.parse_natural("do something", chat_id=7, user_id=2)
    assert req.project == "other"
    assert req.instruction == "do something"


def test_parse_natural_project_option_overrides_chat_preference(project_registry: ProjectRegistry):
    root = project_registry.config_path.parent / "pref2_repo"
    root.mkdir()
    wt = project_registry.config_path.parent / "pref2_wt"
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
    pref = InMemoryProjectPreferenceStore()
    pref.set(7, "other")
    parser = CommandParser(
        project_registry=project_registry,
        default_model=ModelName.CLAUDE,
        project_preferences=pref,
    )
    req = parser.parse_natural("project: remote-coder fix bug", chat_id=7, user_id=2)
    assert req.project == "remote-coder"
    assert req.instruction == "fix bug"


def test_parse_natural_rejects_invalid_branch_token(project_registry: ProjectRegistry):
    parser = CommandParser(project_registry=project_registry, default_model=ModelName.CLAUDE)
    with pytest.raises(CommandParseError, match="브랜치"):
        parser.parse_natural("branch: bad..name fix bug", chat_id=1, user_id=2)


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
    req = parser.parse_natural("작업 시작해줘", chat_id=99, user_id=1)
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
        parser.parse_natural("작업 시작해줘", chat_id=42, user_id=1)


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
        chat_id=99,
        user_id=1,
        message_id=12,
        reply_to_message_id=11,
    )

    assert req.branch == "remote-a"
    assert req.message_id == 12
    assert req.reply_to_message_id == 11
