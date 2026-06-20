import pytest

from app.ai.codex import CodexRunner
from app.ai.factory import AiRunnerFactory, UnknownModelError
from app.ai.gemini import GeminiRunner
from app.ai.ollama import OllamaRunner
from app.models import CodexSandboxMode, ModelName


def test_ai_factory_create_claude():
    runner = AiRunnerFactory().create(ModelName.CLAUDE)
    assert runner.name == "claude"


def test_ai_factory_create_codex():
    runner = AiRunnerFactory().create(ModelName.CODEX)
    assert isinstance(runner, CodexRunner)


def test_ai_factory_create_gemini():
    runner = AiRunnerFactory().create(ModelName.GEMINI)
    assert isinstance(runner, GeminiRunner)


def test_ai_factory_create_ollama():
    runner = AiRunnerFactory().create(ModelName.OLLAMA)
    assert isinstance(runner, OllamaRunner)


def test_ai_factory_passes_codex_sandbox_to_runner():
    runner = AiRunnerFactory(codex_sandbox=CodexSandboxMode.READ_ONLY).create(ModelName.CODEX)
    assert isinstance(runner, CodexRunner)
    assert runner._sandbox == CodexSandboxMode.READ_ONLY


def test_ai_factory_invalid_model():
    with pytest.raises(UnknownModelError):
        AiRunnerFactory().create("x")  # type: ignore[arg-type]
