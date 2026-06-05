from collections.abc import Callable

from app.ai.base import AiRunner
from app.ai.claude import ClaudeRunner
from app.ai.codex import CodexRunner
from app.ai.gemini import GeminiRunner
from app.models import CodexSandboxMode, ModelName


class UnknownModelError(ValueError):
    pass


class AiRunnerFactory:
    def __init__(self, codex_sandbox: CodexSandboxMode = CodexSandboxMode.WORKSPACE_WRITE) -> None:
        self._codex_sandbox = codex_sandbox

    def create(self, model_name: ModelName) -> AiRunner:
        builders: dict[ModelName, Callable[[], AiRunner]] = {
            ModelName.CLAUDE: ClaudeRunner,
            ModelName.CODEX: lambda: CodexRunner(sandbox=self._codex_sandbox),
            ModelName.GEMINI: GeminiRunner,
        }
        builder = builders.get(model_name)
        if builder is None:
            raise UnknownModelError(f"Unsupported model: {model_name}")
        return builder()
