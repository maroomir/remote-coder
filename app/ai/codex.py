from app.ai.base import AiRunner, RunnerInput, RunnerResult


class CodexRunner(AiRunner):
    name = "codex"

    def run(self, runner_input: RunnerInput) -> RunnerResult:
        _ = runner_input
        raise NotImplementedError("Codex runner is planned for Phase 3")
