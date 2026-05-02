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
        if model_name == ModelName.CLAUDE:
            return ClaudeRunner()
        if model_name == ModelName.CODEX:
            return CodexRunner(sandbox=self._codex_sandbox)
        if model_name == ModelName.GEMINI:
            return GeminiRunner()
        raise UnknownModelError(f"Unsupported model: {model_name}")
