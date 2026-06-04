from __future__ import annotations

import subprocess
import threading
from datetime import UTC, datetime

from app.ai.base import AiRunner, RunnerInput, RunnerResult, instruction_for_runner_mode
from app.jobs.schemas import JobMode
from app.monitoring.events import EventLogger

_log = EventLogger("app.ai.gemini", "ai.runner")


class GeminiRunner(AiRunner):
    name = "gemini"

    def run(self, runner_input: RunnerInput) -> RunnerResult:
        cwd_name = runner_input.cwd.name
        _log.info(
            "start cwd=%s timeout=%d instruction_len=%d",
            cwd_name,
            runner_input.timeout_seconds,
            len(runner_input.instruction),
        )
        started_at = datetime.now(UTC)
        if runner_input.mode in (JobMode.PLAN, JobMode.ASK):
            prompt = instruction_for_runner_mode(runner_input.instruction, runner_input.mode)
            argv = ["gemini", "--skip-trust", "-p", prompt]
        else:
            argv = ["gemini", "--approval-mode", "yolo", "--skip-trust", "-p", runner_input.instruction]
        proc = subprocess.Popen(
            argv,
            cwd=runner_input.cwd,
            env=runner_input.env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        _log.info("process spawned pid=%s cwd=%s", proc.pid, cwd_name)
        cancelled = threading.Event()
        if runner_input.cancel_event is not None:
            cancel_event = runner_input.cancel_event

            def _watch() -> None:
                cancel_event.wait()
                if proc.poll() is None:
                    _log.warning("cancel requested pid=%s", proc.pid)
                    proc.terminate()
                cancelled.set()

            threading.Thread(target=_watch, daemon=True).start()
        try:
            stdout_data, stderr_data = proc.communicate(timeout=runner_input.timeout_seconds)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout_data, stderr_data = proc.communicate()
            _log.warning(
                "timeout after %ds stdout_len=%d stderr_len=%d",
                runner_input.timeout_seconds,
                len(stdout_data),
                len(stderr_data),
            )
            raise
        finished_at = datetime.now(UTC)
        if cancelled.is_set():
            raise RuntimeError("작업이 취소되었습니다.")
        dur_ms = int((finished_at - started_at).total_seconds() * 1000)
        _log.info(
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
