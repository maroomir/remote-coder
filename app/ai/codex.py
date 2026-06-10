from __future__ import annotations

from pathlib import Path

from app.ai.base import BaseCliRunner, RunnerInput, instruction_for_runner_mode
from app.jobs.schemas import JobMode
from app.models import CodexSandboxMode
from app.monitoring.events import EventLogger


class CodexRunner(BaseCliRunner):
    name = "codex"
    _log = EventLogger("app.ai.codex", "ai.runner")

    def __init__(self, sandbox: CodexSandboxMode = CodexSandboxMode.WORKSPACE_WRITE) -> None:
        self._sandbox = sandbox

    def _resolve_sandbox(self, runner_input: RunnerInput) -> CodexSandboxMode:
        if runner_input.mode in (JobMode.PLAN, JobMode.ASK):
            return CodexSandboxMode.READ_ONLY
        return self._sandbox

    def _start_log_detail(self, runner_input: RunnerInput) -> str:
        return f" sandbox={self._resolve_sandbox(runner_input).value}"

    def _session_dir(self) -> Path:
        # Codex cannot set a session id upfront, so capture the rollout file it writes here.
        return Path.home() / ".codex" / "sessions"

    def build_argv(self, runner_input: RunnerInput) -> list[str]:
        sandbox = self._resolve_sandbox(runner_input)
        if runner_input.mode in (JobMode.PLAN, JobMode.ASK):
            instruction = instruction_for_runner_mode(runner_input.instruction, runner_input.mode)
        else:
            instruction = runner_input.instruction
        if runner_input.resume_token:
            argv = ["codex", "exec", "resume", runner_input.resume_token]
        else:
            argv = ["codex", "exec"]
        if runner_input.model_id:
            argv.extend(["--model", runner_input.model_id])
        argv.extend(["--sandbox", sandbox.value, instruction])
        return argv
