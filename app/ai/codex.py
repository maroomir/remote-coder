from __future__ import annotations

import subprocess
from datetime import UTC, datetime

from app.ai.base import AiRunner, RunnerInput, RunnerResult
from app.monitoring.events import EventLogger
from app.models import CodexSandboxMode

_log = EventLogger("app.ai.codex", "ai.runner")


class CodexRunner(AiRunner):
    name = "codex"

    def __init__(self, sandbox: CodexSandboxMode = CodexSandboxMode.WORKSPACE_WRITE) -> None:
        self._sandbox = sandbox

    def run(self, runner_input: RunnerInput) -> RunnerResult:
        cwd_name = runner_input.cwd.name
        _log.info("start cwd=%s timeout=%d", cwd_name, runner_input.timeout_seconds)
        started_at = datetime.now(UTC)
        try:
            completed = subprocess.run(
                ["codex", "exec", "--sandbox", self._sandbox.value, runner_input.instruction],
                cwd=runner_input.cwd,
                timeout=runner_input.timeout_seconds,
                env=runner_input.env,
                capture_output=True,
                text=True,
                shell=False,
                check=False,
            )
        except subprocess.TimeoutExpired:
            _log.warning("timeout after %ds", runner_input.timeout_seconds)
            raise
        finished_at = datetime.now(UTC)
        dur_ms = int((finished_at - started_at).total_seconds() * 1000)
        _log.info("done exit=%d dur_ms=%d", completed.returncode, dur_ms)
        return RunnerResult(
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            started_at=started_at,
            finished_at=finished_at,
        )
