from __future__ import annotations

import subprocess
import threading
from datetime import UTC, datetime

from app.ai.base import AiRunner, RunnerInput, RunnerResult
from app.monitoring.events import EventLogger

_log = EventLogger("app.ai.gemini", "ai.runner")


class GeminiRunner(AiRunner):
    name = "gemini"

    def run(self, runner_input: RunnerInput) -> RunnerResult:
        cwd_name = runner_input.cwd.name
        _log.info("start cwd=%s timeout=%d", cwd_name, runner_input.timeout_seconds)
        started_at = datetime.now(UTC)
        proc = subprocess.Popen(
            ["gemini", "--approval-mode", "yolo", "-p", runner_input.instruction],
            cwd=runner_input.cwd,
            env=runner_input.env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        cancelled = threading.Event()
        if runner_input.cancel_event is not None:
            cancel_event = runner_input.cancel_event

            def _watch() -> None:
                cancel_event.wait()
                if proc.poll() is None:
                    proc.terminate()
                cancelled.set()

            threading.Thread(target=_watch, daemon=True).start()
        try:
            stdout_data, stderr_data = proc.communicate(timeout=runner_input.timeout_seconds)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout_data, stderr_data = proc.communicate()
            _log.warning("timeout after %ds", runner_input.timeout_seconds)
            raise
        finished_at = datetime.now(UTC)
        if cancelled.is_set():
            raise RuntimeError("작업이 취소되었습니다.")
        dur_ms = int((finished_at - started_at).total_seconds() * 1000)
        _log.info("done exit=%d dur_ms=%d", proc.returncode, dur_ms)
        return RunnerResult(
            exit_code=proc.returncode,
            stdout=stdout_data,
            stderr=stderr_data,
            started_at=started_at,
            finished_at=finished_at,
        )
