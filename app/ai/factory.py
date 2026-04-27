from app.ai.base import AiRunner
from app.ai.claude import ClaudeRunner
from app.ai.codex import CodexRunner
from app.models import ModelName


class UnknownModelError(ValueError):
    pass


class AiRunnerFactory:
    def create(self, model_name: ModelName) -> AiRunner:
        if model_name == ModelName.CLAUDE:
            return ClaudeRunner()
        if model_name == ModelName.CODEX:
            return CodexRunner()
        raise UnknownModelError(f"Unsupported model: {model_name}")
