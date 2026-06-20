from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from app.ai.base import AiRunner
from app.ai.claude import ClaudeRunner
from app.ai.codex import CodexRunner
from app.ai.gemini import GeminiRunner
from app.ai.ollama import OllamaRunner
from app.models import CodexSandboxMode, ModelName

if TYPE_CHECKING:
    from app.admin.advanced_settings import FileAdvancedSettingsStore


class UnknownModelError(ValueError):
    pass


class AiRunnerFactory:
    def __init__(
        self,
        advanced_settings_store: FileAdvancedSettingsStore | None = None,
        codex_sandbox: CodexSandboxMode = CodexSandboxMode.WORKSPACE_WRITE,
    ) -> None:
        self._advanced_settings_store = advanced_settings_store
        self._codex_sandbox = codex_sandbox

    def _effective_codex_sandbox(self) -> CodexSandboxMode:
        if self._advanced_settings_store is not None:
            return self._advanced_settings_store.get().codex_sandbox
        return self._codex_sandbox

    def create(self, model_name: ModelName) -> AiRunner:
        sandbox = self._effective_codex_sandbox()
        builders: dict[ModelName, Callable[[], AiRunner]] = {
            ModelName.CLAUDE: ClaudeRunner,
            ModelName.CODEX: lambda: CodexRunner(sandbox=sandbox),
            ModelName.GEMINI: GeminiRunner,
            ModelName.OLLAMA: OllamaRunner,
        }
        builder = builders.get(model_name)
        if builder is None:
            raise UnknownModelError(f"Unsupported model: {model_name}")
        return builder()
