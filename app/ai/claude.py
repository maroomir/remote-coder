from __future__ import annotations

from app.ai.base import BaseCliRunner, RunnerInput, instruction_for_runner_mode
from app.monitoring.events import EventLogger


class ClaudeRunner(BaseCliRunner):
    name = "claude"
    _log = EventLogger("app.ai.claude", "ai.runner")

    def _resolve_result_session_id(
        self, runner_input: RunnerInput, before: dict[str, float]
    ) -> str | None:
        # Claude owns its session id deterministically (we pass --session-id/--resume).
        return runner_input.resume_token or runner_input.session_id

    def build_argv(self, runner_input: RunnerInput) -> list[str]:
        prompt = instruction_for_runner_mode(runner_input.instruction, runner_input.mode)
        argv = ["claude", "-p", prompt, "--dangerously-skip-permissions"]
        if runner_input.resume_token:
            argv.extend(["--resume", runner_input.resume_token])
        elif runner_input.session_id:
            argv.extend(["--session-id", runner_input.session_id])
        if runner_input.model_id:
            argv.extend(["--model", runner_input.model_id])
        return argv
