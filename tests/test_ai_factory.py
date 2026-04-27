import pytest

from app.ai.codex import CodexRunner
from app.ai.factory import AiRunnerFactory, UnknownModelError
from app.models import ModelName


def test_ai_factory_create_claude():
    runner = AiRunnerFactory().create(ModelName.CLAUDE)
    assert runner.name == "claude"


def test_ai_factory_create_codex():
    runner = AiRunnerFactory().create(ModelName.CODEX)
    assert isinstance(runner, CodexRunner)


def test_ai_factory_invalid_model():
    with pytest.raises(UnknownModelError):
        AiRunnerFactory().create("x")  # type: ignore[arg-type]
