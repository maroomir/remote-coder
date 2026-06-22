from __future__ import annotations

import re

from app.ai.model_catalog import format_model_selection
from app.jobs.diff_review import DiffReviewSummary
from app.jobs.schemas import Job


def ascii_pr_text(text: str, fallback: str) -> str:
    """Collapse whitespace and keep the text only if it is pure ASCII.

    `gh pr create` body/title travel through the shell and GitHub API; non-ASCII content has
    historically corrupted them, so we fall back to a safe placeholder instead.
    """
    normalized = re.sub(r"\s+", " ", text).strip()
    if normalized and normalized.isascii():
        return normalized
    return fallback


def _model_label(job: Job) -> str:
    return job.runner_actual_model or format_model_selection(job.request.model, job.request.model_id)


def _change_summary_section(review: DiffReviewSummary | None) -> str | None:
    if review is None or not review.files:
        return None
    lines = [
        f"- `{stat.path}` "
        + ("(binary)" if stat.is_binary else f"(+{stat.added or 0}/-{stat.deleted or 0})")
        for stat in review.files
    ]
    header = f"## Change summary ({review.file_count} files, +{review.total_added}/-{review.total_deleted})"
    return header + "\n" + "\n".join(lines)


def _known_limitations_section(review: DiffReviewSummary | None) -> str:
    notes = ["- Automated tests were not run as part of this job; verify before merging."]
    if review is not None and review.risk_flags:
        notes.extend(f"- Risk: {flag}" for flag in review.risk_flags)
    return "## Known limitations\n" + "\n".join(notes)


def build_pr_body(
    branch: str,
    requests: list[tuple[str, str | None]],
    job: Job | None,
) -> str:
    """Assemble a structured PR body from the work request history and the job metadata.

    `requests` is the ordered list of (user_request, ai_result) entries tied to the branch. `job`
    is the latest succeeded job on the branch, used for model, change summary, and risk notes.
    Reuses the diff review summary that the job already computed (feature A).
    """
    sections: list[str] = [f"Work branch: `{branch}`"]

    if job is not None:
        sections.append(f"**Model:** {_model_label(job)}")

    if requests:
        request_lines: list[str] = ["## Work request"]
        for index, (user_text, ai_result) in enumerate(requests, 1):
            if len(requests) > 1:
                request_lines.append(f"### Request {index}")
            safe_request = ascii_pr_text(
                user_text, "Request omitted because it contains non-ASCII text."
            )
            request_lines.append(f"**Request:** {safe_request}")
            if ai_result:
                safe_result = ascii_pr_text(
                    ai_result, "AI result omitted because it contains non-ASCII text."
                )
                request_lines.append(f"\n**AI result:**\n{safe_result}")
        sections.append("\n".join(request_lines))

    review = job.diff_review if job is not None else None
    change_summary = _change_summary_section(review)
    if change_summary is not None:
        sections.append(change_summary)

    sections.append(_known_limitations_section(review))

    return "\n\n".join(sections)
