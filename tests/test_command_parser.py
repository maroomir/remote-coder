import pytest

from app.models import ModelName
from app.projects.registry import ProjectRecord, ProjectRegistry
from app.telegram.model_preferences import InMemoryModelPreferenceStore
from app.telegram.parser import CommandParseError, CommandParser


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
