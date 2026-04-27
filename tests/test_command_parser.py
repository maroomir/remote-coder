import pytest

from app.models import ModelName
from app.telegram.model_preferences import InMemoryModelPreferenceStore
from app.telegram.parser import CommandParseError, CommandParser


def test_parse_natural_returns_job_request():
    parser = CommandParser(default_project="proj", default_model=ModelName.CLAUDE)
    req = parser.parse_natural("fix login bug", chat_id=1, user_id=2)
    assert req.project == "proj"
    assert req.model == ModelName.CLAUDE
    assert req.instruction == "fix login bug"


def test_parse_natural_raises_on_empty():
    parser = CommandParser(default_project="proj", default_model=ModelName.CLAUDE)
    with pytest.raises(CommandParseError):
        parser.parse_natural("   ", chat_id=1, user_id=2)


def test_parse_natural_uses_model_preference():
    pref = InMemoryModelPreferenceStore(default_model=ModelName.CLAUDE)
    pref.set(1, ModelName.CODEX)
    parser = CommandParser(
        default_project="proj",
        default_model=ModelName.CLAUDE,
        model_preferences=pref,
    )
    req = parser.parse_natural("fix login bug", chat_id=1, user_id=2)
    assert req.model == ModelName.CODEX


def test_parse_natural_parses_model_branch_and_no_commit():
    parser = CommandParser(default_project="proj", default_model=ModelName.CLAUDE)
    req = parser.parse_natural(
        "model: codex branch: remote/test no commit fix login bug",
        chat_id=1,
        user_id=2,
    )
    assert req.model == ModelName.CODEX
    assert req.branch == "remote/test"
    assert not req.commit
    assert req.instruction == "fix login bug"
