from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

from app.git.service import GitWorktreeService
from app.jobs.schemas import Job, JobStatus
from app.jobs.store import JobStore
from app.monitoring.events import EventLogger
from app.projects.registry import ProjectRegistry

SERVER_RESTART_ERROR = "server restarted while this job was running"
SERVER_RESTART_STAGE = "server_restart"


def recover_startup_jobs(
    *,
    job_store: JobStore,
    run_job: Callable[[str], Job | None],
    record_final_job_result: Callable[[Job], None] | None,
    system_log: EventLogger,
) -> threading.Thread | None:
    running_jobs = job_store.list_latest_by_status([JobStatus.RUNNING])
    for job in running_jobs:
        job.mark_failed(SERVER_RESTART_ERROR)
        job.error_stage = SERVER_RESTART_STAGE
        job_store.update(job)
        system_log.info(
            "startup recovery marked running job failed",
            project=job.request.project,
            job_id=job.id,
            chat_id=job.request.chat_id,
        )

    queued_jobs = job_store.list_latest_by_status([JobStatus.QUEUED])
    if not queued_jobs:
        return None

    job_ids = [job.id for job in queued_jobs]
    system_log.info("startup recovery queued jobs=%d", len(job_ids))

    def _run_recovered_jobs() -> None:
        for job_id in job_ids:
            latest = job_store.get(job_id)
            if latest is None or latest.status is not JobStatus.QUEUED:
                continue
            try:
                system_log.info(
                    "startup recovery rerunning queued job",
                    project=latest.request.project,
                    job_id=job_id,
                    chat_id=latest.request.chat_id,
                )
                final_job = run_job(job_id)
                if final_job is not None and record_final_job_result is not None:
                    record_final_job_result(final_job)
            except Exception:
                system_log.exception("startup recovery queued job failed", job_id=job_id)

    thread = threading.Thread(
        target=_run_recovered_jobs,
        name="remote-coder-startup-job-recovery",
        daemon=True,
    )
    thread.start()
    return thread


def run_startup_project_pulls(
    *,
    pull_projects_on_server_startup_enabled: bool,
    project_registry: ProjectRegistry,
    git_service: GitWorktreeService,
    remote: str,
    system_log: EventLogger,
) -> None:
    if not pull_projects_on_server_startup_enabled:
        return

    roots: dict[Path, str] = {}
    for record in project_registry.list_projects():
        if not record.enabled:
            continue
        path = record.root_path.resolve()
        if path not in roots:
            roots[path] = record.name

    for root_path, project_name in roots.items():
        try:
            summary = git_service.pull_repository(root_path, remote)
            system_log.info("startup pull completed: %s", summary, project=project_name)
        except Exception:
            system_log.exception("startup pull failed", project=project_name)
