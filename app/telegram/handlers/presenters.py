from __future__ import annotations

from app.ai.model_catalog import format_model_selection
from app.jobs.schemas import JobMode, JobRequest, is_read_only_job_mode
from app.telegram.commands import InlineButton
from app.telegram.commands import NAV_CLOSE_CALLBACK

NATURAL_JOB_CONFIRMATION = "__natural_job__"
NATURAL_JOB_CONFIRM_YES = "__natural_job__:yes"
NATURAL_JOB_CONFIRM_NO = "__natural_job__:no"
NATURAL_JOB_MODE_INPUT = "__natural_job_mode_input__"
CLOSE_PANEL = NAV_CLOSE_CALLBACK
TELEGRAM_TEXT_LIMIT = 4096


def format_natural_job_confirmation(
    request: JobRequest,
    current_branch: str,
) -> str:
    lines = [
        "Confirm the work to run.",
        "",
        f"- Project: {request.project}",
        f"- Work branch: {current_branch}",
        f"- Model: {format_model_selection(request.model, request.model_id)}",
    ]
    if is_read_only_job_mode(request.mode):
        lines.append(f"- Mode: {request.mode.value} (read-only, no commit/push)")
    else:
        lines.append("- Mode: agent (may edit code, commit, and push)")
    if request.branch:
        lines.append(f"- Requested branch: {request.branch}")
    lines.extend(["", "Choose whether to run it."])
    return "\n".join(lines)


def format_fix_source_confirmation(
    request: JobRequest,
    target_job,
) -> str:
    lines = [
        "Confirm the fix job.",
        "",
        f"- Project: {request.project}",
        f"- Target Job: {target_job.id}",
        f"- Branch: {target_job.branch}",
        f"- Original commit: {target_job.commit_hash}",
        f"- Model: {format_model_selection(request.model, request.model_id)}",
        "- Mode: fix (amends the existing commit and pushes with --force-with-lease)",
        "",
        "Choose whether to run it.",
    ]
    return "\n".join(lines)


def natural_job_confirmation_buttons() -> list[list[InlineButton]]:
    return [[InlineButton("Yes", NATURAL_JOB_CONFIRM_YES), InlineButton("No", NATURAL_JOB_CONFIRM_NO)]]


def format_natural_job_cancelled(request: JobRequest | None) -> str:
    if request is None:
        return "Cancelled the work request."
    return (
        "Cancelled the work request. "
        f"(project: {request.project}, model: {format_model_selection(request.model, request.model_id)})"
    )


def format_mode_input_prompt(mode: JobMode) -> str:
    if mode is JobMode.PLAN:
        return (
            "Send the instruction to run in plan mode.\n\n"
            "Example: Plan a login fix\n"
            "Example: model: codex List only API boundary risks"
        )
    if mode is JobMode.ASK:
        return (
            "Send the question to run in ask mode.\n\n"
            "Example: Explain the JobManager flow\n"
            "Example: model: codex How do I run pytest?"
        )
    if mode is JobMode.RESEARCH:
        return (
            "Send the research question to run in research mode.\n\n"
            "Example: Compare FastAPI deployment options for this project\n"
            "Example: model: codex Research the safest webhook retry strategy"
        )
    raise AssertionError(mode)


def format_fix_mode_input_prompt() -> str:
    return (
        "Send the fix instruction to run in fix mode.\n\n"
        "Example: add missing tests\n"
        "Example: fix: patch the login validation bug"
    )


def format_fix_requires_reply_message() -> str:
    return (
        "Fix mode requires replying to a job result message.\n\n"
        "Example: reply to a job result, then send /fix\n"
        "Example: reply to a job result with fix: add missing tests"
    )
