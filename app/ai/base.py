from __future__ import annotations

import re
import subprocess
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from app.jobs.schemas import JobMode
from app.monitoring.events import EventLogger


_SESSION_UUID_PATTERN = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


class RunnerExecutionError(RuntimeError):
    # Carries the partial output captured before a runner was killed (timeout/cancel) so the
    # job layer can still persist and surface what the model produced.
    def __init__(
        self,
        message: str,
        *,
        stdout: str = "",
        stderr: str = "",
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
    ) -> None:
        super().__init__(message)
        self.stdout = stdout
        self.stderr = stderr
        self.started_at = started_at or datetime.now(UTC)
        self.finished_at = finished_at or datetime.now(UTC)



_PLAN_DECISIONS_INSTRUCTION = (
    "You are in PLAN mode. Read the codebase and produce a concrete change plan. "
    "Do not modify files.\n\n"
    "Before finalizing, decide whether the plan depends on choices only the user can make "
    "(for example: which library/database to use, reuse an existing module vs. create a new one, "
    "scope or behavior trade-offs). If such open decisions exist, do NOT write the plan yet. "
    "Instead output ONLY a single fenced block exactly like this and nothing else:\n"
    "```plan-decisions\n"
    '{"questions": [{"id": "short_id", "header": "Short label", '
    '"question": "The decision to make?", "options": ['
    '{"label": "Option A", "description": "What this choice means"}, '
    '{"label": "Option B", "description": "What this choice means"}]}]}\n'
    "```\n"
    "Rules for the block: at most 3 questions; each question has 2-4 options; keep labels short "
    "and descriptions to one sentence; valid JSON only. If there are no genuine open decisions, "
    "skip the block entirely and just write the plan as usual.\n\n"
    "User request:\n"
)


def instruction_for_runner_mode(instruction: str, mode: JobMode) -> str:
    if mode == JobMode.PLAN:
        return f"{_PLAN_DECISIONS_INSTRUCTION}{instruction}"
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
    session_id: str | None = None
    resume_token: str | None = None
    native_resume_cwd_stable: bool = True


@dataclass
class RunnerResult:
    exit_code: int
    stdout: str
    stderr: str
    started_at: datetime
    finished_at: datetime
    session_id: str | None = None


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

    def _session_dir(self) -> Path | None:
        # Providers that auto-generate a session id (Codex/Gemini) override this so the
        # base run loop can capture the new session file written during the run.
        return None

    @staticmethod
    def _session_id_from_name(name: str) -> str | None:
        match = _SESSION_UUID_PATTERN.search(name)
        return match.group(0) if match else None

    def _snapshot_session_files(self) -> dict[str, float]:
        directory = self._session_dir()
        if directory is None or not directory.exists():
            return {}
        snapshot: dict[str, float] = {}
        for path in directory.rglob("*"):
            if not path.is_file():
                continue
            try:
                snapshot[str(path)] = path.stat().st_mtime
            except OSError:
                continue
        return snapshot

    def _capture_new_session_id(self, before: dict[str, float]) -> str | None:
        directory = self._session_dir()
        if directory is None or not directory.exists():
            return None
        newest_id: str | None = None
        newest_mtime = -1.0
        for path in directory.rglob("*"):
            if not path.is_file():
                continue
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if str(path) in before and mtime <= before[str(path)]:
                continue
            session_id = self._session_id_from_name(path.name)
            if session_id is not None and mtime > newest_mtime:
                newest_mtime = mtime
                newest_id = session_id
        return newest_id

    def _resolve_result_session_id(
        self, runner_input: RunnerInput, before: dict[str, float]
    ) -> str | None:
        # Capture-based providers (Codex/Gemini): keep the resumed token, otherwise read the
        # id the CLI just wrote. Return None when nothing is captured so we never resume a
        # session the provider does not actually own.
        if runner_input.resume_token:
            return runner_input.resume_token
        return self._capture_new_session_id(before)

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
        session_files_before = self._snapshot_session_files()
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
        except subprocess.TimeoutExpired as exc:
            proc.kill()
            stdout_data, stderr_data = proc.communicate()
            self._log.warning(
                "timeout after %ds stdout_len=%d stderr_len=%d",
                runner_input.timeout_seconds,
                len(stdout_data),
                len(stderr_data),
            )
            raise RunnerExecutionError(
                f"runner timed out after {runner_input.timeout_seconds}s",
                stdout=stdout_data,
                stderr=stderr_data,
                started_at=started_at,
            ) from exc
        finished_at = datetime.now(UTC)
        if cancelled.is_set():
            raise RunnerExecutionError(
                "The job was cancelled.",
                stdout=stdout_data,
                stderr=stderr_data,
                started_at=started_at,
                finished_at=finished_at,
            )
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
            session_id=self._resolve_result_session_id(runner_input, session_files_before),
        )
