from __future__ import annotations

import threading
from pathlib import Path

from app.ai.base import RunnerInput
from app.git.commit_message import CommitMessageFormatter
from app.jobs.plan_decisions import PlanDecisionQuestion, parse_plan_decisions
from app.jobs.schemas import Job, JobMode
from app.monitoring.events import EventLogger

_joblog = EventLogger("app.jobs.lifecycle", "job.lifecycle")


def run_job(manager, job_id: str) -> Job:
    job = manager._job_store.get(job_id)
    if not job:
        _joblog.warning("run requested for missing job job_id=%s", job_id)
        raise ValueError("job not found")

    if job_id in manager._cancelled_job_ids:
        if job.status.value != "cancelled":
            job.mark_cancelled()
            manager._job_store.update(job)
        manager._send_result(job)
        return job

    cancel_event = threading.Event()
    manager._cancel_events[job_id] = cancel_event
    _joblog.info("cancel event registered", **manager._job_ctx(job))

    entry = manager._project_registry.get(job.request.project)
    if not entry or not entry.enabled:
        _joblog.warning("unknown/disabled project", **manager._job_ctx(job))
        job.mark_failed("unknown or disabled project")
        job.error_stage = "project_resolve"
        manager._job_store.update(job)
        manager._send_result(job)
        return job

    project_path = entry.root_path
    worktree_base = entry.worktree_base_dir
    _joblog.info(
        "project resolved default_model=%s worktree_base=%s",
        entry.default_model.value,
        worktree_base.name,
        **manager._job_ctx(job),
    )
    worktree_path: Path | None = None
    created_worktree_for_job = False
    failed_stage: str | None = None
    remote = manager._effective_git_remote_name()
    read_only_job = job.request.mode in (JobMode.PLAN, JobMode.ASK)
    plan_decision_questions: list[PlanDecisionQuestion] | None = None
    try:
        job.mark_running()
        manager._job_store.update(job)
        _joblog.info("running", **manager._job_ctx(job))

        failed_stage = "git_worktree"
        _joblog.info("stage=git_worktree", **manager._job_ctx(job))
        plan = manager._prepare_worktree_plan(job, project_path, worktree_base)
        worktree_path = plan.path
        created_worktree_for_job = plan.created_for_job
        worktree_on_branch = plan.on_branch
        commit_to_requested_branch = plan.commit_to_requested_branch
        manager._git_service.ensure_worktree_writable(worktree_path)
        _joblog.info("worktree writable", **manager._job_ctx(job))

        failed_stage = "runner"
        _joblog.info(
            "stage=runner model=%s model_id=%s",
            job.request.model.value,
            job.request.model_id or "-",
            **manager._job_ctx(job),
        )
        runner = manager._runner_factory.create(job.request.model)
        timeout_seconds = manager._effective_job_timeout_seconds()
        _joblog.info(
            "runner created name=%s timeout=%d instruction_len=%d",
            getattr(runner, "name", job.request.model.value),
            timeout_seconds,
            len(job.request.instruction),
            **manager._job_ctx(job),
        )
        heartbeat = manager._start_heartbeat(job)
        try:
            runner_result = runner.run(
                RunnerInput(
                    instruction=job.request.instruction,
                    cwd=worktree_path,
                    timeout_seconds=timeout_seconds,
                    model_id=job.request.model_id,
                    env=None,
                    cancel_event=cancel_event,
                    mode=job.request.mode,
                    session_id=job.request.session_id,
                    resume_token=job.request.resume_session_token,
                    native_resume_cwd_stable=not created_worktree_for_job,
                )
            )
        finally:
            heartbeat.set()
        manager._save_runner_log(job, runner_result, worktree_base)
        _joblog.info(
            "runner exit=%d stdout_len=%d stderr_len=%d",
            runner_result.exit_code,
            len(runner_result.stdout),
            len(runner_result.stderr),
            **manager._job_ctx(job),
        )

        if runner_result.exit_code != 0:
            raise RuntimeError(runner_result.stderr.strip() or "runner failed")

        if read_only_job:
            job.branch = None
            job.commit_hash = None
            job.changed_files = []
            job.mark_succeeded()
            manager._job_store.update(job)
            _joblog.info(
                "succeeded read_only mode=%s", job.request.mode.value, **manager._job_ctx(job)
            )
            if job.request.mode is JobMode.PLAN and not job.request.plan_decisions_resolved:
                plan_decision_questions = parse_plan_decisions(runner_result.stdout)
        else:
            failed_stage = "git_commit"
            _joblog.info("stage=git_commit", **manager._job_ctx(job))
            job.changed_files = manager._git_service.collect_changes(worktree_path)
            _joblog.info("changes=%d", len(job.changed_files), **manager._job_ctx(job))

            if not job.changed_files:
                job.branch = None
                job.commit_hash = None
                job.mark_succeeded()
                manager._job_store.update(job)
                _joblog.info("succeeded branch=%s commit=%s", "-", "-", **manager._job_ctx(job))
            else:
                job.branch = (
                    job.request.branch
                    if commit_to_requested_branch
                    else manager._branch_strategy.make_branch_name(job.request.instruction)
                )
                manager._job_store.update(job)
                _joblog.info(
                    "branch selected branch=%s requested=%s",
                    job.branch,
                    commit_to_requested_branch,
                    **manager._job_ctx(job),
                )
                if not worktree_on_branch:
                    manager._git_service.create_branch_in_worktree(worktree_path, job.branch)
                    worktree_on_branch = True
                    _joblog.info(
                        "branch created in worktree branch=%s", job.branch, **manager._job_ctx(job)
                    )
                job.changed_files = manager._git_service.collect_changes(worktree_path)

                if job.request.commit:
                    ai_title = None
                    ai_body = None
                    if manager._ai_commit_body_generator is not None:
                        ai_title, ai_body = manager._ai_commit_body_generator.generate(
                            instruction=job.request.instruction,
                            changed_files=job.changed_files,
                            model_name=job.request.model,
                        )
                    commit_message = CommitMessageFormatter.format(
                        job_id=job.id,
                        instruction=job.request.instruction,
                        changed_files=job.changed_files,
                        ai_body=ai_body,
                        ai_title=ai_title,
                    )
                    _joblog.info(
                        "commit message ready changed_files=%d ai_title=%s ai_body=%s",
                        len(job.changed_files),
                        ai_title is not None,
                        ai_body is not None,
                        **manager._job_ctx(job),
                    )
                    job.commit_hash = manager._git_service.commit_all(worktree_path, commit_message)
                    _joblog.info(
                        "commit result hash=%s", job.commit_hash or "-", **manager._job_ctx(job)
                    )
                else:
                    job.commit_hash = None
                    _joblog.info("commit skipped by request", **manager._job_ctx(job))

                if job.request.commit and job.commit_hash:
                    failed_stage = "git_push"
                    _joblog.info("stage=git_push", **manager._job_ctx(job))
                    manager._git_service.push_branch(project_path, remote, job.branch)

                if (
                    manager._advanced_settings_store is not None
                    and manager._advanced_settings_store.get().auto_merge_to_main_enabled
                    and job.request.commit
                    and job.commit_hash
                    and job.branch
                ):
                    failed_stage = "git_integrate_main"
                    _joblog.info("stage=git_integrate_main", **manager._job_ctx(job))
                    ops_base = worktree_base / "_rebase_ops"
                    manager._git_service.rebase_branch_onto_main_and_merge(
                        project_path,
                        job.branch,
                        remote,
                        ops_base,
                    )

                job.mark_succeeded()
                manager._job_store.update(job)
                _joblog.info(
                    "succeeded branch=%s commit=%s",
                    job.branch or "-",
                    job.commit_hash or "-",
                    **manager._job_ctx(job),
                )
    except Exception as exc:  # pylint: disable=broad-except
        manager._preserve_partial_output(job, exc, worktree_base)
        if job_id in manager._cancelled_job_ids:
            _joblog.info("runner stopped by cancellation", **manager._job_ctx(job))
            if job.status.value != "cancelled":
                job.mark_cancelled()
                manager._job_store.update(job)
        else:
            _joblog.exception(
                "failed stage=%s: %s",
                failed_stage or "unknown",
                exc,
                **manager._job_ctx(job),
            )
            job.mark_failed(str(exc))
            job.error_stage = failed_stage or "unknown"
            manager._job_store.update(job)
    finally:
        manager._cancel_events.pop(job_id, None)
        manager._cancelled_job_ids.discard(job_id)
        read_only_succeeded = (
            job.request.mode in (JobMode.PLAN, JobMode.ASK) and job.status.value == "succeeded"
        )
        cleanup_on_success = read_only_succeeded or not manager._effective_keep_worktree_on_success()
        _joblog.info(
            "job finalizing status=%s created_worktree=%s cleanup_on_success=%s",
            job.status.value,
            created_worktree_for_job,
            cleanup_on_success,
            **manager._job_ctx(job),
        )
        if (
            worktree_path
            and created_worktree_for_job
            and job.status.value == "succeeded"
            and cleanup_on_success
        ):
            try:
                manager._git_service.cleanup_worktree(project_path, worktree_path)
                _joblog.info("worktree cleanup done", **manager._job_ctx(job))
            except RuntimeError as exc:
                # cleanup 실패로 성공 Job 알림이 누락되지 않도록 삼킵니다.
                _joblog.warning(
                    "worktree cleanup failed but result notification continues: %s",
                    exc,
                    **manager._job_ctx(job),
                )
        if not manager._route_plan_decisions(job, plan_decision_questions):
            manager._send_result(job)
    return job
