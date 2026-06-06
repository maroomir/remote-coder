from __future__ import annotations

import subprocess
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from app.jobs.schemas import JobMode
from app.monitoring.events import EventLogger


def instruction_for_runner_mode(instruction: str, mode: JobMode) -> str:
    if mode == JobMode.PLAN:
        return (
            "You are in PLAN mode. Read the codebase and produce a concrete change plan. "
            "Do not modify files.\n\n"
            f"User request:\n{instruction}"
        )
    if mode == JobMode.ASK:
        return (
            "You are in ASK mode. Analyze the codebase and answer the user's question. "
            "Do not modify files.\n\n"
            f"User question:\n{instruction}"
        )
    return instruction


@dataclass
class RunnerInput:
    instruction: str
    cwd: Path
    timeout_seconds: int
    model_id: str | None = None
    env: dict[str, str] | None = None
    cancel_event: threading.Event | None = field(default=None, compare=False)
    mode: JobMode = JobMode.AGENT


@dataclass
class RunnerResult:
    exit_code: int
    stdout: str
    stderr: str
    started_at: datetime
    finished_at: datetime


class AiRunner(ABC):
    name: str

    @abstractmethod
    def run(self, runner_input: RunnerInput) -> RunnerResult:
        raise NotImplementedError


class BaseCliRunner(AiRunner):
    _log: EventLogger

    @abstractmethod
    def build_argv(self, runner_input: RunnerInput) -> list[str]:
        raise NotImplementedError

    def _start_log_detail(self, runner_input: RunnerInput) -> str:
        return ""

    def run(self, runner_input: RunnerInput) -> RunnerResult:
        cwd_name = runner_input.cwd.name
        self._log.info(
            "start cwd=%s timeout=%d%s instruction_len=%d",
            cwd_name,
            runner_input.timeout_seconds,
            self._start_log_detail(runner_input),
            len(runner_input.instruction),
        )
        started_at = datetime.now(UTC)
        argv = self.build_argv(runner_input)
        proc = subprocess.Popen(
            argv,
            cwd=runner_input.cwd,
            env=runner_input.env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self._log.info("process spawned pid=%s cwd=%s", proc.pid, cwd_name)
        cancelled = threading.Event()
        if runner_input.cancel_event is not None:
            cancel_event = runner_input.cancel_event

            def _watch() -> None:
                cancel_event.wait()
                if proc.poll() is None:
                    self._log.warning("cancel requested pid=%s", proc.pid)
                    proc.terminate()
                cancelled.set()

            threading.Thread(target=_watch, daemon=True).start()
        try:
            stdout_data, stderr_data = proc.communicate(timeout=runner_input.timeout_seconds)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout_data, stderr_data = proc.communicate()
            self._log.warning(
                "timeout after %ds stdout_len=%d stderr_len=%d",
                runner_input.timeout_seconds,
                len(stdout_data),
                len(stderr_data),
            )
            raise
        finished_at = datetime.now(UTC)
        if cancelled.is_set():
            raise RuntimeError("The job was cancelled.")
        dur_ms = int((finished_at - started_at).total_seconds() * 1000)
        self._log.info(
            "done exit=%d dur_ms=%d stdout_len=%d stderr_len=%d",
            proc.returncode,
            dur_ms,
            len(stdout_data),
            len(stderr_data),
        )
        return RunnerResult(
            exit_code=proc.returncode,
            stdout=stdout_data,
            stderr=stderr_data,
            started_at=started_at,
            finished_at=finished_at,
        )
