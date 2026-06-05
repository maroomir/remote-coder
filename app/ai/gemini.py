from __future__ import annotations

from app.ai.base import BaseCliRunner, RunnerInput, instruction_for_runner_mode
from app.jobs.schemas import JobMode
from app.monitoring.events import EventLogger


class GeminiRunner(BaseCliRunner):
    name = "gemini"
    _log = EventLogger("app.ai.gemini", "ai.runner")

    def build_argv(self, runner_input: RunnerInput) -> list[str]:
        if runner_input.mode in (JobMode.PLAN, JobMode.ASK):
            prompt = instruction_for_runner_mode(runner_input.instruction, runner_input.mode)
            argv = ["gemini", "--skip-trust", "-p", prompt]
        else:
            argv = ["gemini", "--approval-mode", "yolo", "--skip-trust", "-p", runner_input.instruction]
        if runner_input.model_id:
            argv.extend(["--model", runner_input.model_id])
        return argv
