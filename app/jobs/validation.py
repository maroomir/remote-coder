from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.monitoring.events import EventLogger

_joblog = EventLogger("app.jobs.validation", "job.validation")

# Cap the captured output so a chatty test suite cannot bloat the job record or the Telegram
# failure summary; the tail is the most useful part of a failing test run.
_OUTPUT_TAIL_LIMIT = 2000


@dataclass(frozen=True, slots=True)
class ValidationResult:
    passed: bool
    exit_code: int | None
    output_summary: str
    timed_out: bool = False


def _tail(text: str, limit: int = _OUTPUT_TAIL_LIMIT) -> str:
    stripped = text.strip()
    if len(stripped) <= limit:
        return stripped
    return "…" + stripped[-limit:]


def run_validation_command(
    command: str,
    worktree_path: Path,
    timeout_seconds: int,
) -> ValidationResult:
    """Run the project's validation command in the worktree and report whether it passed.

    The command is split with shlex (no shell), so it is a plain argv invocation rather than an
    arbitrary shell string. A non-zero exit, a timeout, or a missing executable all count as a
    failed validation; the gate caller then preserves the changes uncommitted.
    """
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        _joblog.warning("validation command parse failed: %s", exc)
        return ValidationResult(
            passed=False,
            exit_code=None,
            output_summary=f"Could not parse validation command: {exc}",
        )
    if not argv:
        return ValidationResult(
            passed=False,
            exit_code=None,
            output_summary="Validation command is empty.",
        )

    _joblog.info("validation start argv0=%s timeout=%d", argv[0], timeout_seconds)
    try:
        result = subprocess.run(
            argv,
            cwd=worktree_path,
            capture_output=True,
            text=True,
            check=False,
            shell=False,
            timeout=timeout_seconds,
        )
    except FileNotFoundError:
        _joblog.warning("validation command not found argv0=%s", argv[0])
        return ValidationResult(
            passed=False,
            exit_code=None,
            output_summary=f"Validation command not found: {argv[0]}",
        )
    except subprocess.TimeoutExpired:
        _joblog.warning("validation timed out after %ds argv0=%s", timeout_seconds, argv[0])
        return ValidationResult(
            passed=False,
            exit_code=None,
            output_summary=f"Validation command timed out after {timeout_seconds}s.",
            timed_out=True,
        )

    combined = _tail((result.stdout or "") + ("\n" + result.stderr if result.stderr else ""))
    passed = result.returncode == 0
    _joblog.info("validation done exit=%d passed=%s", result.returncode, passed)
    return ValidationResult(
        passed=passed,
        exit_code=result.returncode,
        output_summary=combined,
    )
