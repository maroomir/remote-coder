from __future__ import annotations

from pathlib import Path

from app.ai.base import BaseCliRunner, RunnerInput, instruction_for_runner_mode
from app.jobs.schemas import is_read_only_job_mode
from app.monitoring.events import EventLogger


class GeminiRunner(BaseCliRunner):
    name = "gemini"
    _log = EventLogger("app.ai.gemini", "ai.runner")

    def _session_dir(self) -> Path:
        # Best-effort capture; when Gemini does not expose a resumable session id here the
        # session simply falls back to prompt-injected reply context.
        return Path.home() / ".gemini" / "sessions"

    def build_argv(self, runner_input: RunnerInput) -> list[str]:
        if is_read_only_job_mode(runner_input.mode):
            prompt = instruction_for_runner_mode(runner_input.instruction, runner_input.mode)
            argv = ["gemini", "--skip-trust", "-p", prompt]
        else:
            argv = ["gemini", "--approval-mode", "yolo", "--skip-trust", "-p", runner_input.instruction]
        if runner_input.resume_token:
            argv.extend(["--resume", runner_input.resume_token])
        if runner_input.model_id:
            argv.extend(["--model", runner_input.model_id])
        return argv
