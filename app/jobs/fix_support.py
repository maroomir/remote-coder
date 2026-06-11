from __future__ import annotations

from app.jobs.schemas import Job, JobMode, JobStatus
from app.jobs.store import JobStore


def is_fix_candidate(job: Job, project: str, chat_id: int) -> bool:
    return (
        job.request.project == project
        and job.request.chat_id == chat_id
        and job.status == JobStatus.SUCCEEDED
        and bool(job.branch)
        and bool(job.commit_hash)
    )


def list_fix_candidates(
    job_store: JobStore,
    project: str,
    chat_id: int,
    limit: int = 8,
) -> list[Job]:
    return [
        job
        for job in job_store.list_recent_for_project_chat(project, chat_id, limit * 4)
        if is_fix_candidate(job, project, chat_id)
    ][:limit]


def resolve_fix_target_job(
    job_store: JobStore,
    job_id: str,
    project: str,
    chat_id: int,
) -> Job | None:
    job = job_store.get(job_id)
    if job is None:
        return None
    visited: set[str] = set()
    while job is not None and job.id not in visited:
        visited.add(job.id)
        if is_fix_candidate(job, project, chat_id):
            if job.request.mode is JobMode.AGENT_FIX and job.request.parent_job_id:
                parent = job_store.get(job.request.parent_job_id)
                if parent is not None and is_fix_candidate(parent, project, chat_id):
                    return parent
            return job
        if job.request.parent_job_id:
            job = job_store.get(job.request.parent_job_id)
        else:
            break
    return None


def compose_fix_source_prompt(parent_job: Job, fix_instruction: str) -> str:
    original_files = (
        "\n".join(f"- {path}" for path in parent_job.changed_files)
        if parent_job.changed_files
        else "(none)"
    )
    return (
        "[Original request]\n"
        f"{parent_job.request.instruction.strip()}\n\n"
        "[Original changed files]\n"
        f"{original_files}\n\n"
        "[User follow-up fix request]\n"
        f"{fix_instruction.strip()}\n\n"
        "Apply the requested fix on top of the existing work. "
        "Do not add new files or unrelated changes."
    )
