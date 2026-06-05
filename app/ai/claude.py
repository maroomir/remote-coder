from __future__ import annotations

from app.ai.base import BaseCliRunner, RunnerInput, instruction_for_runner_mode
from app.jobs.schemas import JobMode
from app.monitoring.events import EventLogger


class ClaudeRunner(BaseCliRunner):
    name = "claude"
    _log = EventLogger("app.ai.claude", "ai.runner")

    def build_argv(self, runner_input: RunnerInput) -> list[str]:
        if runner_input.mode in (JobMode.PLAN, JobMode.ASK):
            prompt = instruction_for_runner_mode(runner_input.instruction, runner_input.mode)
            argv = ["claude", "-p", prompt, "--permission-mode", "plan"]
        else:
            argv = ["claude", "-p", runner_input.instruction, "--dangerously-skip-permissions"]
        if runner_input.model_id:
            argv.extend(["--model", runner_input.model_id])
        return argv
