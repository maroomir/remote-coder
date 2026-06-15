from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from app.ai.base import RunnerExecutionError, RunnerResult
from app.ai.usage import extract_runner_usage
from app.jobs.schemas import Job
from app.monitoring.events import EventLogger

_joblog = EventLogger("app.jobs.lifecycle", "job.lifecycle")

_ANSI_ESCAPE_PATTERN = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
_MD_LINK_PATTERN = re.compile(r"\[([^\]]*)\]\([^)]+\)")
_HTTP_URL_PATTERN = re.compile(r"https?://[^\s\]\)>,]+", flags=re.IGNORECASE)
_WWW_URL_PATTERN = re.compile(r"\bwww\.[^\s\]\)>,]+", flags=re.IGNORECASE)
STDOUT_SUMMARY_LIMIT = 12000
STDERR_SUMMARY_LIMIT = 800


class IncrementalRunnerLog:
    def __init__(
        self,
        job: Job,
        worktree_base: Path,
        update_job: Callable[[Job], None],
        *,
        update_interval_seconds: float = 1.0,
    ) -> None:
        self._job = job
        self._update_job = update_job
        self._update_interval_seconds = update_interval_seconds
        self._stdout_parts: list[str] = []
        self._stderr_parts: list[str] = []
        self._lock = threading.Lock()
        self._started_at = datetime.now(UTC)
        self._last_update = 0.0
        log_dir = worktree_base / "_logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        self._path = log_dir / f"{job.id}.log"
        self._job.log_path = self._path
        with self._lock:
            self._write_log_locked(exit_code="running", finished_at=None)
            self._refresh_summaries_locked()
        self._update_job(self._job)

    def output_callback(self, stream: Literal["stdout", "stderr"], chunk: str) -> None:
        if not chunk:
            return
        with self._lock:
            if stream == "stdout":
                self._stdout_parts.append(chunk)
            else:
                self._stderr_parts.append(chunk)
            self._write_log_locked(exit_code="running", finished_at=None)
            self._refresh_summaries_locked()
            now = time.monotonic()
            if now - self._last_update < self._update_interval_seconds:
                return
            self._last_update = now
        self._update_job(self._job)

    def flush(self) -> None:
        with self._lock:
            self._refresh_summaries_locked()
        self._update_job(self._job)

    def _write_log_locked(self, *, exit_code: int | str, finished_at: datetime | None) -> None:
        log_text = _runner_log_text(
            self._job,
            exit_code=exit_code,
            started_at=self._started_at,
            finished_at=finished_at,
            stdout="".join(self._stdout_parts),
            stderr="".join(self._stderr_parts),
        )
        self._path.write_text(log_text, encoding="utf-8")

    def _refresh_summaries_locked(self) -> None:
        self._job.runner_stdout_summary = make_output_summary(
            "".join(self._stdout_parts),
            limit=STDOUT_SUMMARY_LIMIT,
            strip_links=True,
        )
        self._job.runner_stderr_summary = make_output_summary(
            "".join(self._stderr_parts),
            limit=STDERR_SUMMARY_LIMIT,
        )


def start_incremental_runner_log(
    job: Job,
    worktree_base: Path,
    update_job: Callable[[Job], None],
) -> IncrementalRunnerLog:
    return IncrementalRunnerLog(job, worktree_base, update_job)


def preserve_partial_output(job: Job, exc: BaseException, worktree_base: Path) -> None:
    # A timed-out or cancelled runner still produced output; persist it so the failure
    # notification can surface the log path and an output summary.
    if not isinstance(exc, RunnerExecutionError):
        return
    save_runner_log(
        job,
        RunnerResult(
            exit_code=-1,
            stdout=exc.stdout,
            stderr=exc.stderr,
            started_at=exc.started_at,
            finished_at=exc.finished_at,
        ),
        worktree_base,
    )


def save_runner_log(job: Job, runner_result, worktree_base: Path) -> None:
    log_dir = worktree_base / "_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{job.id}.log"
    log_text = _runner_log_text(
        job,
        exit_code=runner_result.exit_code,
        started_at=runner_result.started_at,
        finished_at=runner_result.finished_at,
        stdout=runner_result.stdout,
        stderr=runner_result.stderr,
    )
    log_path.write_text(log_text, encoding="utf-8")
    job.log_path = log_path
    job.runner_stdout_summary = make_output_summary(
        runner_result.stdout,
        limit=STDOUT_SUMMARY_LIMIT,
        strip_links=True,
    )
    job.runner_stderr_summary = make_output_summary(
        runner_result.stderr, limit=STDERR_SUMMARY_LIMIT
    )
    usage = extract_runner_usage(f"{runner_result.stdout}\n{runner_result.stderr}")
    job.runner_actual_model = usage.actual_model
    job.runner_token_usage = usage.token_usage
    job.runner_session_id = runner_result.session_id
    _joblog.info(
        "runner log saved file=%s stdout_summary=%s stderr_summary=%s actual_model=%s token_usage=%s",
        log_path.name,
        job.runner_stdout_summary is not None,
        job.runner_stderr_summary is not None,
        job.runner_actual_model or "-",
        bool(job.runner_token_usage),
        chat_id=job.request.chat_id,
        user_id=job.request.requested_by,
        project=job.request.project,
        job_id=job.id,
    )


def _runner_log_text(
    job: Job,
    *,
    exit_code: int | str,
    started_at: datetime | None,
    finished_at: datetime | None,
    stdout: str,
    stderr: str,
) -> str:
    return (
        f"job_id={job.id}\n"
        f"model={job.request.model.value}\n"
        f"exit_code={exit_code}\n"
        f"started_at={started_at}\n"
        f"finished_at={finished_at}\n\n"
        f"[stdout]\n{stdout}\n\n"
        f"[stderr]\n{stderr}\n"
    )


def extract_stdout_from_log(path: Path) -> str | None:
    """Return the full [stdout] section of a saved runner log, ANSI-stripped."""
    try:
        log_text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    marker = "\n[stdout]\n"
    start = log_text.find(marker)
    if start == -1:
        return None
    start += len(marker)
    stderr_at = log_text.rfind("\n\n[stderr]\n")
    stdout = log_text[start:stderr_at] if stderr_at >= start else log_text[start:]
    stdout = _ANSI_ESCAPE_PATTERN.sub("", stdout)
    return stdout or None


def strip_links_for_stdout_summary(text: str) -> str:
    stripped = _MD_LINK_PATTERN.sub(r"\1", text)
    stripped = _HTTP_URL_PATTERN.sub("", stripped)
    stripped = _WWW_URL_PATTERN.sub("", stripped)
    stripped = re.sub(r"[ \t]{2,}", " ", stripped)
    return stripped


def make_output_summary(
    text: str,
    limit: int,
    *,
    strip_links: bool = False,
) -> str | None:
    if not text:
        return None
    no_ansi = _ANSI_ESCAPE_PATTERN.sub("", text)
    if strip_links:
        no_ansi = strip_links_for_stdout_summary(no_ansi)
    normalized = "\n".join(line.rstrip() for line in no_ansi.splitlines()).strip()
    if not normalized:
        return None
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit].rstrip()}...(truncated)"
