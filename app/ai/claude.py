from __future__ import annotations

import subprocess
from datetime import UTC, datetime

from app.ai.base import AiRunner, RunnerInput, RunnerResult


class ClaudeRunner(AiRunner):
    name = "claude"

    def run(self, runner_input: RunnerInput) -> RunnerResult:
        started_at = datetime.now(UTC)
        completed = subprocess.run(
            ["claude", "-p", runner_input.instruction, "--dangerously-skip-permissions"],
            cwd=runner_input.cwd,
            timeout=runner_input.timeout_seconds,
            env=runner_input.env,
            capture_output=True,
            text=True,
            shell=False,
            check=False,
        )
        finished_at = datetime.now(UTC)
        return RunnerResult(
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            started_at=started_at,
            finished_at=finished_at,
        )
