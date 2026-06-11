from __future__ import annotations

import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.admin.advanced_settings import FileAdvancedSettingsStore
from app.ai.base import RunnerInput
from app.ai.factory import AiRunnerFactory
from app.ai.usage import extract_runner_usage
from app.config import Settings
from app.git.ai_commit import AiCommitBodyGenerator
from app.git.branch_naming import BranchNamingStrategy
from app.git.commit_message import CommitMessageFormatter
from app.git.service import GitWorktreeService
from app.jobs.plan_decisions import PlanDecisionQuestion, parse_plan_decisions
from app.jobs.schemas import FixKind, Job, JobMode, JobRequest, JobStatus
from app.jobs.store import JobStore
from app.monitoring.events import EventLogger
from app.projects.registry import ProjectRegistry
from app.telegram.notifier import Notifier

_joblog = EventLogger("app.jobs.lifecycle", "job.lifecycle")


@dataclass
class _WorktreePlan:
    path: Path
    created_for_job: bool
    on_branch: bool
    commit_to_requested_branch: bool


class JobManager:
    _ANSI_ESCAPE_PATTERN = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
    _MD_LINK_PATTERN = re.compile(r"\[([^\]]*)\]\([^)]+\)")
    _HTTP_URL_PATTERN = re.compile(r"https?://[^\s\]\)>,]+", flags=re.IGNORECASE)
    _WWW_URL_PATTERN = re.compile(r"\bwww\.[^\s\]\)>,]+", flags=re.IGNORECASE)
    _STDOUT_SUMMARY_LIMIT = 12000
    _STDERR_SUMMARY_LIMIT = 800

    def __init__(
        self,
        settings: Settings,
        job_store: JobStore,
        git_service: GitWorktreeService,
        runner_factory: AiRunnerFactory,
        branch_strategy: BranchNamingStrategy,
        notifier_resolver: Callable[[str], Notifier],
        project_registry: ProjectRegistry,
        advanced_settings_store: FileAdvancedSettingsStore | None = None,
        ai_commit_body_generator: AiCommitBodyGenerator | None = None,
        plan_decision_router: Callable[[Job, list[PlanDecisionQuestion]], bool] | None = None,
    ) -> None:
        self._settings = settings
        self._job_store = job_store
        self._git_service = git_service
        self._runner_factory = runner_factory
        self._branch_strategy = branch_strategy
        self._notifier_resolver = notifier_resolver
        self._project_registry = project_registry
        self._advanced_settings_store = advanced_settings_store
        self._ai_commit_body_generator = ai_commit_body_generator
        # Set post-construction by the Telegram layer (mirrors command_context.job_manager).
        self.plan_decision_router = plan_decision_router
        self._cancel_events: dict[str, threading.Event] = {}
        self._cancelled_job_ids: set[str] = set()

    def _notifier_for(self, project: str) -> Notifier:
        return self._notifier_resolver(project)

    @staticmethod
    def _job_ctx(job: Job) -> dict[str, object]:
        return {
            "chat_id": job.request.chat_id,
            "user_id": job.request.requested_by,
            "project": job.request.project,
            "job_id": job.id,
        }

    @staticmethod
    def _message_id_or_none(value: object) -> int | None:
        return value if isinstance(value, int) else None

    @staticmethod
    def _message_ids_or_empty(value: object) -> list[int]:
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, int)]

    def _send_result(self, job: Job) -> None:
        job.result_message_ids = self._message_ids_or_empty(
            self._notifier_for(job.request.project).send_job_result(job)
        )
        self._job_store.update(job)

    def submit(self, request: JobRequest) -> Job:
        job = Job(id=request.job_id or self._make_job_id(), request=request)
        self._job_store.create(job)
        _joblog.info(
            "submitted model=%s model_id=%s",
            request.model.value,
            request.model_id or "-",
            **self._job_ctx(job),
        )
        accepted_message_id = self._message_id_or_none(
            self._notifier_for(request.project).send_job_accepted(job)
        )
        if accepted_message_id is not None:
            job.accepted_message_id = accepted_message_id
            self._job_store.update(job)
        return job

    def cancel(self, job_id: str) -> bool:
        job = self._job_store.get(job_id)
        if not job:
            _joblog.warning("cancel requested for missing job job_id=%s", job_id)
            return False
        if job.status.value not in ("queued", "running"):
            _joblog.info("cancel skipped status=%s", job.status.value, **self._job_ctx(job))
            return False
        self._cancelled_job_ids.add(job_id)
        job.mark_cancelled()
        self._job_store.update(job)
        _joblog.info("cancelled", **self._job_ctx(job))
        event = self._cancel_events.get(job_id)
        if event is not None:
            event.set()
        return True

    def _prepare_worktree_plan(
        self, job: Job, project_path: Path, worktree_base: Path
    ) -> _WorktreePlan:
        requested_branch = job.request.branch
        if job.request.mode in (JobMode.PLAN, JobMode.ASK):
            path = self._git_service.prepare_detached_worktree(
                project_path, job.id, worktree_base_dir=worktree_base
            )
            _joblog.info(
                "created detached worktree mode=%s worktree=%s",
                job.request.mode.value,
                path.name,
                **self._job_ctx(job),
            )
            return _WorktreePlan(path, created_for_job=True, on_branch=False, commit_to_requested_branch=False)

        if requested_branch and self._git_service.local_branch_exists(project_path, requested_branch):
            _joblog.info("requested branch exists branch=%s", requested_branch, **self._job_ctx(job))
            existing_worktree = self._git_service.find_linked_worktree_for_branch(
                project_path, requested_branch
            )
            if existing_worktree is not None:
                _joblog.info(
                    "reuse linked worktree branch=%s worktree=%s",
                    requested_branch,
                    existing_worktree.name,
                    **self._job_ctx(job),
                )
                return _WorktreePlan(
                    existing_worktree, created_for_job=False, on_branch=True, commit_to_requested_branch=True
                )
            if self._git_service.branch_is_checked_out(project_path, requested_branch):
                path = self._git_service.prepare_detached_worktree(
                    project_path, job.id, worktree_base_dir=worktree_base, base_branch=requested_branch
                )
                _joblog.info(
                    "created detached worktree from checked-out branch branch=%s worktree=%s",
                    requested_branch,
                    path.name,
                    **self._job_ctx(job),
                )
                return _WorktreePlan(
                    path, created_for_job=True, on_branch=False, commit_to_requested_branch=False
                )
            path = self._git_service.prepare_branch_worktree(
                project_path, requested_branch, job.id, worktree_base_dir=worktree_base
            )
            _joblog.info(
                "created branch worktree branch=%s worktree=%s",
                requested_branch,
                path.name,
                **self._job_ctx(job),
            )
            return _WorktreePlan(path, created_for_job=True, on_branch=True, commit_to_requested_branch=True)

        path = self._git_service.prepare_detached_worktree(
            project_path, job.id, worktree_base_dir=worktree_base
        )
        _joblog.info(
            "created detached worktree requested_branch=%s worktree=%s",
            requested_branch or "-",
            path.name,
            **self._job_ctx(job),
        )
        return _WorktreePlan(
            path,
            created_for_job=True,
            on_branch=False,
            commit_to_requested_branch=requested_branch is not None,
        )

    def run(self, job_id: str) -> Job:
        job = self._job_store.get(job_id)
        if not job:
            _joblog.warning("run requested for missing job job_id=%s", job_id)
            raise ValueError("job not found")

        if job_id in self._cancelled_job_ids:
            if job.status.value != "cancelled":
                job.mark_cancelled()
                self._job_store.update(job)
            self._send_result(job)
            return job

        cancel_event = threading.Event()
        self._cancel_events[job_id] = cancel_event
        _joblog.info("cancel event registered", **self._job_ctx(job))

        entry = self._project_registry.get(job.request.project)
        if not entry or not entry.enabled:
            _joblog.warning("unknown/disabled project", **self._job_ctx(job))
            job.mark_failed("unknown or disabled project")
            job.error_stage = "project_resolve"
            self._job_store.update(job)
            self._send_result(job)
            return job

        project_path = entry.root_path
        worktree_base = entry.worktree_base_dir
        _joblog.info(
            "project resolved default_model=%s worktree_base=%s",
            entry.default_model.value,
            worktree_base.name,
            **self._job_ctx(job),
        )
        worktree_path: Path | None = None
        created_worktree_for_job = False
        failed_stage: str | None = None
        remote = self._effective_git_remote_name()
        read_only_job = job.request.mode in (JobMode.PLAN, JobMode.ASK)
        plan_decision_questions: list[PlanDecisionQuestion] | None = None
        try:
            job.mark_running()
            self._job_store.update(job)
            _joblog.info("running", **self._job_ctx(job))

            failed_stage = "git_worktree"
            _joblog.info("stage=git_worktree", **self._job_ctx(job))
            plan = self._prepare_worktree_plan(job, project_path, worktree_base)
            worktree_path = plan.path
            created_worktree_for_job = plan.created_for_job
            worktree_on_branch = plan.on_branch
            commit_to_requested_branch = plan.commit_to_requested_branch
            self._git_service.ensure_worktree_writable(worktree_path)
            _joblog.info("worktree writable", **self._job_ctx(job))

            failed_stage = "runner"
            _joblog.info(
                "stage=runner model=%s model_id=%s",
                job.request.model.value,
                job.request.model_id or "-",
                **self._job_ctx(job),
            )
            runner = self._runner_factory.create(job.request.model)
            timeout_seconds = self._effective_job_timeout_seconds()
            _joblog.info(
                "runner created name=%s timeout=%d instruction_len=%d",
                getattr(runner, "name", job.request.model.value),
                timeout_seconds,
                len(job.request.instruction),
                **self._job_ctx(job),
            )
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
                )
            )
            self._save_runner_log(job, runner_result, worktree_base)
            _joblog.info(
                "runner exit=%d stdout_len=%d stderr_len=%d",
                runner_result.exit_code,
                len(runner_result.stdout),
                len(runner_result.stderr),
                **self._job_ctx(job),
            )

            if runner_result.exit_code != 0:
                raise RuntimeError(runner_result.stderr.strip() or "runner failed")

            if read_only_job:
                job.branch = None
                job.commit_hash = None
                job.changed_files = []
                job.mark_succeeded()
                self._job_store.update(job)
                _joblog.info(
                    "succeeded read_only mode=%s", job.request.mode.value, **self._job_ctx(job)
                )
                if job.request.mode is JobMode.PLAN and not job.request.plan_decisions_resolved:
                    plan_decision_questions = parse_plan_decisions(runner_result.stdout)
            else:
                failed_stage = "git_commit"
                _joblog.info("stage=git_commit", **self._job_ctx(job))
                job.changed_files = self._git_service.collect_changes(worktree_path)
                _joblog.info("changes=%d", len(job.changed_files), **self._job_ctx(job))

                if not job.changed_files:
                    job.branch = None
                    job.commit_hash = None
                    job.mark_succeeded()
                    self._job_store.update(job)
                    _joblog.info("succeeded branch=%s commit=%s", "-", "-", **self._job_ctx(job))
                else:
                    job.branch = (
                        job.request.branch
                        if commit_to_requested_branch
                        else self._branch_strategy.make_branch_name(job.request.instruction)
                    )
                    self._job_store.update(job)
                    _joblog.info(
                        "branch selected branch=%s requested=%s",
                        job.branch,
                        commit_to_requested_branch,
                        **self._job_ctx(job),
                    )
                    if not worktree_on_branch:
                        self._git_service.create_branch_in_worktree(worktree_path, job.branch)
                        worktree_on_branch = True
                        _joblog.info(
                            "branch created in worktree branch=%s", job.branch, **self._job_ctx(job)
                        )
                    job.changed_files = self._git_service.collect_changes(worktree_path)

                    if job.request.commit:
                        ai_title = None
                        ai_body = None
                        if self._ai_commit_body_generator is not None:
                            ai_title, ai_body = self._ai_commit_body_generator.generate(
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
                            **self._job_ctx(job),
                        )
                        job.commit_hash = self._git_service.commit_all(worktree_path, commit_message)
                        _joblog.info(
                            "commit result hash=%s", job.commit_hash or "-", **self._job_ctx(job)
                        )
                    else:
                        job.commit_hash = None
                        _joblog.info("commit skipped by request", **self._job_ctx(job))

                    if job.request.commit and job.commit_hash:
                        failed_stage = "git_push"
                        _joblog.info("stage=git_push", **self._job_ctx(job))
                        self._git_service.push_branch(project_path, remote, job.branch)

                    if (
                        self._advanced_settings_store is not None
                        and self._advanced_settings_store.get().auto_merge_to_main_enabled
                        and job.request.commit
                        and job.commit_hash
                        and job.branch
                    ):
                        failed_stage = "git_integrate_main"
                        _joblog.info("stage=git_integrate_main", **self._job_ctx(job))
                        ops_base = worktree_base / "_rebase_ops"
                        self._git_service.rebase_branch_onto_main_and_merge(
                            project_path,
                            job.branch,
                            remote,
                            ops_base,
                        )

                    job.mark_succeeded()
                    self._job_store.update(job)
                    _joblog.info(
                        "succeeded branch=%s commit=%s",
                        job.branch or "-",
                        job.commit_hash or "-",
                        **self._job_ctx(job),
                    )
        except Exception as exc:  # pylint: disable=broad-except
            if job_id in self._cancelled_job_ids:
                _joblog.info("runner stopped by cancellation", **self._job_ctx(job))
                if job.status.value != "cancelled":
                    job.mark_cancelled()
                    self._job_store.update(job)
            else:
                _joblog.exception(
                    "failed stage=%s: %s",
                    failed_stage or "unknown",
                    exc,
                    **self._job_ctx(job),
                )
                job.mark_failed(str(exc))
                job.error_stage = failed_stage or "unknown"
                self._job_store.update(job)
        finally:
            self._cancel_events.pop(job_id, None)
            self._cancelled_job_ids.discard(job_id)
            read_only_succeeded = (
                job.request.mode in (JobMode.PLAN, JobMode.ASK) and job.status.value == "succeeded"
            )
            cleanup_on_success = read_only_succeeded or not self._effective_keep_worktree_on_success()
            _joblog.info(
                "job finalizing status=%s created_worktree=%s cleanup_on_success=%s",
                job.status.value,
                created_worktree_for_job,
                cleanup_on_success,
                **self._job_ctx(job),
            )
            if (
                worktree_path
                and created_worktree_for_job
                and job.status.value == "succeeded"
                and cleanup_on_success
            ):
                try:
                    self._git_service.cleanup_worktree(project_path, worktree_path)
                    _joblog.info("worktree cleanup done", **self._job_ctx(job))
                except RuntimeError as exc:
                    # cleanup 실패로 성공 Job 알림이 누락되지 않도록 삼킵니다.
                    _joblog.warning(
                        "worktree cleanup failed but result notification continues: %s",
                        exc,
                        **self._job_ctx(job),
                    )
            if not self._route_plan_decisions(job, plan_decision_questions):
                self._send_result(job)
        return job

    def _route_plan_decisions(
        self, job: Job, questions: list[PlanDecisionQuestion] | None
    ) -> bool:
        # When the PLAN runner asked for user decisions, hand off to the Telegram layer to
        # collect answers via inline buttons instead of sending the raw block as a plan.
        if not questions or self.plan_decision_router is None:
            return False
        try:
            handled = self.plan_decision_router(job, questions)
        except Exception:  # pylint: disable=broad-except
            _joblog.exception("plan decision router failed", **self._job_ctx(job))
            return False
        if handled:
            _joblog.info(
                "plan decisions routed questions=%d", len(questions), **self._job_ctx(job)
            )
        return handled

    def is_fix_candidate(self, job: Job, project: str, chat_id: int) -> bool:
        return (
            job.request.project == project
            and job.request.chat_id == chat_id
            and job.status == JobStatus.SUCCEEDED
            and bool(job.branch)
            and bool(job.commit_hash)
        )

    def list_fix_candidates(self, project: str, chat_id: int, limit: int = 8) -> list[Job]:
        return [
            job
            for job in self._job_store.list_recent_for_project_chat(project, chat_id, limit * 4)
            if self.is_fix_candidate(job, project, chat_id)
        ][:limit]

    def resolve_fix_target_job(self, job_id: str, project: str, chat_id: int) -> Job | None:
        job = self._job_store.get(job_id)
        if job is None:
            return None
        visited: set[str] = set()
        while job is not None and job.id not in visited:
            visited.add(job.id)
            if self.is_fix_candidate(job, project, chat_id):
                if job.request.mode is JobMode.AGENT_FIX and job.request.parent_job_id:
                    parent = self._job_store.get(job.request.parent_job_id)
                    if parent is not None and self.is_fix_candidate(parent, project, chat_id):
                        return parent
                return job
            if job.request.parent_job_id:
                job = self._job_store.get(job.request.parent_job_id)
            else:
                break
        return None

    @staticmethod
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

    def execute_fix_job(self, request: JobRequest) -> Job:
        if request.mode is not JobMode.AGENT_FIX:
            raise ValueError("execute_fix_job requires JobMode.AGENT_FIX")
        if request.fix_kind is not FixKind.SOURCE:
            raise ValueError("execute_fix_job requires FixKind.SOURCE")
        if not request.parent_job_id:
            raise ValueError("execute_fix_job requires parent_job_id")

        job = Job(id=request.job_id or self._make_job_id(), request=request)
        self._job_store.create(job)
        _joblog.info(
            "fix submitted kind=%s parent=%s",
            request.fix_kind.value,
            request.parent_job_id,
            **self._job_ctx(job),
        )
        accepted_message_id = self._message_id_or_none(
            self._notifier_for(request.project).send_job_accepted(job)
        )
        if accepted_message_id is not None:
            job.accepted_message_id = accepted_message_id
            self._job_store.update(job)
        return self._run_fix(job.id)

    def _run_fix(self, job_id: str) -> Job:
        job = self._job_store.get(job_id)
        if job is None:
            _joblog.warning("run_fix requested for missing job job_id=%s", job_id)
            raise ValueError("job not found")

        cancel_event = threading.Event()
        self._cancel_events[job_id] = cancel_event

        entry = self._project_registry.get(job.request.project)
        if not entry or not entry.enabled:
            job.mark_failed("unknown or disabled project")
            job.error_stage = "project_resolve"
            self._job_store.update(job)
            self._send_result(job)
            self._cancel_events.pop(job_id, None)
            return job

        project_path = entry.root_path
        worktree_base = entry.worktree_base_dir
        remote = self._effective_git_remote_name()
        worktree_path: Path | None = None
        created_worktree_for_job = False
        failed_stage: str | None = None

        try:
            job.mark_running()
            self._job_store.update(job)

            failed_stage = "fix_resolve_target"
            parent_job = self.resolve_fix_target_job(
                job.request.parent_job_id or "",
                job.request.project,
                job.request.chat_id,
            )
            if parent_job is None:
                raise RuntimeError("Fix target job was not found or can no longer be fixed.")
            assert parent_job.branch is not None
            assert parent_job.commit_hash is not None

            failed_stage = "fix_worktree"
            existing = self._git_service.find_linked_worktree_for_branch(
                project_path, parent_job.branch
            )
            if existing is not None:
                worktree_path = existing
            else:
                worktree_path = self._git_service.prepare_branch_worktree(
                    project_path,
                    parent_job.branch,
                    job.id,
                    worktree_base_dir=worktree_base,
                )
                created_worktree_for_job = True
            self._git_service.ensure_worktree_writable(worktree_path)

            failed_stage = "fix_runner"
            runner = self._runner_factory.create(job.request.model)
            timeout_seconds = self._effective_job_timeout_seconds()
            fix_prompt = self.compose_fix_source_prompt(parent_job, job.request.instruction)
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
                )
            )
            self._save_runner_log(job, runner_result, worktree_base)
            if runner_result.exit_code != 0:
                raise RuntimeError(runner_result.stderr.strip() or "runner failed")

            failed_stage = "fix_collect_changes"
            new_changed = self._git_service.collect_changes(worktree_path)
            merged = list(dict.fromkeys([*parent_job.changed_files, *new_changed]))
            job.changed_files = merged

            if not new_changed:
                job.branch = parent_job.branch
                job.commit_hash = parent_job.commit_hash
                job.mark_succeeded()
                self._job_store.update(job)
                _joblog.info(
                    "fix source produced no changes parent=%s",
                    parent_job.id,
                    **self._job_ctx(job),
                )
            else:
                failed_stage = "fix_message"
                ai_title = None
                ai_body = None
                if self._ai_commit_body_generator is not None:
                    ai_title, ai_body = self._ai_commit_body_generator.generate(
                        instruction=self.compose_fix_source_prompt(
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
                job.commit_hash = self._git_service.amend_commit(worktree_path, commit_message)
                job.branch = parent_job.branch

                failed_stage = "fix_push"
                self._git_service.push_branch_force_with_lease(
                    project_path, remote, parent_job.branch
                )

                parent_job.commit_hash = job.commit_hash
                parent_job.changed_files = merged
                self._job_store.update(parent_job)

                job.mark_succeeded()
                self._job_store.update(job)
        except Exception as exc:  # pylint: disable=broad-except
            _joblog.exception(
                "fix failed stage=%s parent=%s: %s",
                failed_stage or "unknown",
                job.request.parent_job_id or "-",
                exc,
                **self._job_ctx(job),
            )
            if job.status.value != "failed":
                job.mark_failed(str(exc))
            job.error_stage = failed_stage or "unknown"
            self._job_store.update(job)
        finally:
            self._cancel_events.pop(job_id, None)
            if (
                worktree_path is not None
                and created_worktree_for_job
                and job.status.value == "succeeded"
                and not self._effective_keep_worktree_on_success()
            ):
                try:
                    self._git_service.cleanup_worktree(project_path, worktree_path)
                except RuntimeError as cleanup_exc:
                    _joblog.warning(
                        "fix worktree cleanup failed: %s",
                        cleanup_exc,
                        **self._job_ctx(job),
                    )
            self._send_result(job)
        return job

    @staticmethod
    def _make_job_id() -> str:
        ts = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        return f"job_{ts}_{uuid4().hex[:6]}"

    def _effective_job_timeout_seconds(self) -> int:
        if self._advanced_settings_store is None:
            return 1800
        return self._advanced_settings_store.get().job_timeout_seconds

    def _effective_git_remote_name(self) -> str:
        if self._advanced_settings_store is None:
            return "origin"
        return self._advanced_settings_store.get().git_remote_name

    def _effective_keep_worktree_on_success(self) -> bool:
        if self._advanced_settings_store is None:
            return True
        return self._advanced_settings_store.get().keep_worktree_on_success

    def _save_runner_log(self, job: Job, runner_result, worktree_base: Path) -> None:
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
        job.runner_stdout_summary = self._make_output_summary(
            runner_result.stdout,
            limit=self._STDOUT_SUMMARY_LIMIT,
            strip_links=True,
        )
        job.runner_stderr_summary = self._make_output_summary(
            runner_result.stderr, limit=self._STDERR_SUMMARY_LIMIT
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
            **self._job_ctx(job),
        )

    @classmethod
    def _strip_links_for_stdout_summary(cls, text: str) -> str:
        stripped = cls._MD_LINK_PATTERN.sub(r"\1", text)
        stripped = cls._HTTP_URL_PATTERN.sub("", stripped)
        stripped = cls._WWW_URL_PATTERN.sub("", stripped)
        stripped = re.sub(r"[ \t]{2,}", " ", stripped)
        return stripped

    @classmethod
    def _make_output_summary(
        cls,
        text: str,
        limit: int,
        *,
        strip_links: bool = False,
    ) -> str | None:
        if not text:
            return None
        no_ansi = cls._ANSI_ESCAPE_PATTERN.sub("", text)
        if strip_links:
            no_ansi = cls._strip_links_for_stdout_summary(no_ansi)
        normalized = "\n".join(line.rstrip() for line in no_ansi.splitlines()).strip()
        if not normalized:
            return None
        if len(normalized) <= limit:
            return normalized
        return f"{normalized[:limit].rstrip()}...(truncated)"
