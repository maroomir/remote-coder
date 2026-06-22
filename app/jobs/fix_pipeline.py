from __future__ import annotations

import threading
from pathlib import Path

from app.ai.base import RunnerInput
from app.git.commit_message import CommitMessageFormatter
from app.jobs.schemas import Job, JobMode
from app.monitoring.events import EventLogger

_joblog = EventLogger("app.jobs.lifecycle", "job.lifecycle")


def run_fix_job(manager, job_id: str) -> Job:
    job = manager._job_store.get(job_id)
    if job is None:
        _joblog.warning("run_fix requested for missing job job_id=%s", job_id)
        raise ValueError("job not found")

    if job_id in manager._cancelled_job_ids:
        if job.status.value != "cancelled":
            job.mark_cancelled()
            manager._job_store.update(job)
        manager._cancelled_job_ids.discard(job_id)
        manager._send_result(job)
        return job

    cancel_event = threading.Event()
    manager._cancel_events[job_id] = cancel_event

    entry = manager._project_registry.get(job.request.project)
    if not entry or not entry.enabled:
        job.mark_failed("unknown or disabled project")
        job.error_stage = "project_resolve"
        manager._job_store.update(job)
        manager._send_result(job)
        manager._cancel_events.pop(job_id, None)
        return job

    project_path = entry.root_path
    worktree_base = entry.worktree_base_dir
    remote = manager._effective_git_remote_name()
    worktree_path: Path | None = None
    created_worktree_for_job = False
    failed_stage: str | None = None

    try:
        job.mark_running()
        manager._job_store.update(job)

        failed_stage = "fix_resolve_target"
        parent_job = manager.resolve_fix_target_job(
            job.request.parent_job_id or "",
            job.request.project,
            job.request.chat_id,
        )
        if parent_job is None:
            raise RuntimeError("Fix target job was not found or can no longer be fixed.")
        assert parent_job.branch is not None
        assert parent_job.commit_hash is not None

        failed_stage = "fix_worktree"
        existing = manager._git_service.find_linked_worktree_for_branch(
            project_path, parent_job.branch
        )
        if existing is not None:
            worktree_path = existing
        else:
            worktree_path = manager._git_service.prepare_branch_worktree(
                project_path,
                parent_job.branch,
                job.id,
                worktree_base_dir=worktree_base,
            )
            created_worktree_for_job = True
        manager._git_service.ensure_worktree_writable(worktree_path)

        failed_stage = "fix_runner"
        runner = manager._runner_factory.create(job.request.model)
        timeout_seconds = manager._effective_job_timeout_seconds()
        fix_prompt = manager.compose_fix_source_prompt(parent_job, job.request.instruction)
        runner_log = manager._start_incremental_runner_log(job, worktree_base)
        heartbeat = manager._start_heartbeat(job)
        try:
            runner_result = runner.run(
                RunnerInput(
                    instruction=fix_prompt,
                    cwd=worktree_path,
                    timeout_seconds=timeout_seconds,
                    model_id=job.request.model_id,
                    env=None,
                    cancel_event=cancel_event,
                    mode=JobMode.AGENT,
                    session_id=job.request.session_id,
                    resume_token=job.request.resume_session_token,
                    native_resume_cwd_stable=not created_worktree_for_job,
                    output_callback=runner_log.output_callback,
                )
            )
        finally:
            heartbeat.set()
            runner_log.flush()
        manager._save_runner_log(job, runner_result, worktree_base)
        if runner_result.exit_code != 0:
            raise RuntimeError(runner_result.stderr.strip() or "runner failed")

        failed_stage = "fix_collect_changes"
        new_changed = manager._git_service.collect_changes(worktree_path)
        merged = list(dict.fromkeys([*parent_job.changed_files, *new_changed]))
        job.changed_files = merged

        if not new_changed:
            job.branch = parent_job.branch
            job.commit_hash = parent_job.commit_hash
            job.mark_succeeded()
            manager._job_store.update(job)
            _joblog.info(
                "fix source produced no changes parent=%s",
                parent_job.id,
                **manager._job_ctx(job),
            )
        else:
            job.diff_review = manager._build_diff_review(job, worktree_path)
            failed_stage = "fix_message"
            ai_title = None
            ai_body = None
            if manager._ai_commit_body_generator is not None:
                ai_title, ai_body = manager._ai_commit_body_generator.generate(
                    instruction=manager.compose_fix_source_prompt(
                        parent_job, job.request.instruction
                    ),
                    changed_files=merged,
                    model_name=job.request.model,
                )
            commit_message = CommitMessageFormatter.format(
                job_id=parent_job.id,
                instruction=parent_job.request.instruction,
                changed_files=merged,
                ai_body=ai_body,
                ai_title=ai_title,
            )

            failed_stage = "fix_amend"
            job.commit_hash = manager._git_service.amend_commit(worktree_path, commit_message)
            job.branch = parent_job.branch

            failed_stage = "fix_push"
            manager._git_service.push_branch_force_with_lease(
                project_path, remote, parent_job.branch
            )

            parent_job.commit_hash = job.commit_hash
            parent_job.changed_files = merged
            manager._job_store.update(parent_job)

            job.mark_succeeded()
            manager._job_store.update(job)
    except Exception as exc:  # pylint: disable=broad-except
        manager._preserve_partial_output(job, exc, worktree_base)
        _joblog.exception(
            "fix failed stage=%s parent=%s: %s",
            failed_stage or "unknown",
            job.request.parent_job_id or "-",
            exc,
            **manager._job_ctx(job),
        )
        if job.status.value != "failed":
            job.mark_failed(str(exc))
        job.error_stage = failed_stage or "unknown"
        manager._job_store.update(job)
    finally:
        manager._cancel_events.pop(job_id, None)
        if (
            worktree_path is not None
            and created_worktree_for_job
            and job.status.value == "succeeded"
            and not manager._effective_keep_worktree_on_success()
        ):
            try:
                manager._git_service.cleanup_worktree(project_path, worktree_path)
            except RuntimeError as cleanup_exc:
                _joblog.warning(
                    "fix worktree cleanup failed: %s",
                    cleanup_exc,
                    **manager._job_ctx(job),
                )
        manager._send_result(job)
    return job
