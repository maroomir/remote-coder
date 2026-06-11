from __future__ import annotations

import re
from pathlib import Path

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
    log_text = (
        f"job_id={job.id}\n"
        f"model={job.request.model.value}\n"
        f"exit_code={runner_result.exit_code}\n"
        f"started_at={runner_result.started_at}\n"
        f"finished_at={runner_result.finished_at}\n\n"
        f"[stdout]\n{runner_result.stdout}\n\n"
        f"[stderr]\n{runner_result.stderr}\n"
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
