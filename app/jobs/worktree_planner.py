from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.git.service import GitWorktreeService
from app.jobs.schemas import Job, is_read_only_job_mode
from app.monitoring.events import EventLogger

_joblog = EventLogger("app.jobs.lifecycle", "job.lifecycle")


@dataclass
class WorktreePlan:
    path: Path
    created_for_job: bool
    on_branch: bool
    commit_to_requested_branch: bool


def prepare_worktree_plan(
    *,
    job: Job,
    project_path: Path,
    worktree_base: Path,
    git_service: GitWorktreeService,
    job_ctx: dict[str, object],
) -> WorktreePlan:
    requested_branch = job.request.branch
    if is_read_only_job_mode(job.request.mode):
        path = git_service.prepare_detached_worktree(
            project_path, job.id, worktree_base_dir=worktree_base
        )
        _joblog.info(
            "created detached worktree mode=%s worktree=%s",
            job.request.mode.value,
            path.name,
            **job_ctx,
        )
        return WorktreePlan(path, created_for_job=True, on_branch=False, commit_to_requested_branch=False)

    if requested_branch and git_service.local_branch_exists(project_path, requested_branch):
        _joblog.info("requested branch exists branch=%s", requested_branch, **job_ctx)
        existing_worktree = git_service.find_linked_worktree_for_branch(
            project_path, requested_branch
        )
        if existing_worktree is not None:
            _joblog.info(
                "reuse linked worktree branch=%s worktree=%s",
                requested_branch,
                existing_worktree.name,
                **job_ctx,
            )
            return WorktreePlan(
                existing_worktree, created_for_job=False, on_branch=True, commit_to_requested_branch=True
            )
        if git_service.branch_is_checked_out(project_path, requested_branch):
            path = git_service.prepare_detached_worktree(
                project_path, job.id, worktree_base_dir=worktree_base, base_branch=requested_branch
            )
            _joblog.info(
                "created detached worktree from checked-out branch branch=%s worktree=%s",
                requested_branch,
                path.name,
                **job_ctx,
            )
            return WorktreePlan(
                path, created_for_job=True, on_branch=False, commit_to_requested_branch=False
            )
        path = git_service.prepare_branch_worktree(
            project_path, requested_branch, job.id, worktree_base_dir=worktree_base
        )
        _joblog.info(
            "created branch worktree branch=%s worktree=%s",
            requested_branch,
            path.name,
            **job_ctx,
        )
        return WorktreePlan(path, created_for_job=True, on_branch=True, commit_to_requested_branch=True)

    path = git_service.prepare_detached_worktree(
        project_path, job.id, worktree_base_dir=worktree_base
    )
    _joblog.info(
        "created detached worktree requested_branch=%s worktree=%s",
        requested_branch or "-",
        path.name,
        **job_ctx,
    )
    return WorktreePlan(
        path,
        created_for_job=True,
        on_branch=False,
        commit_to_requested_branch=requested_branch is not None,
    )
