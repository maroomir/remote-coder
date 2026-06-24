from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.admin.advanced_settings import FileAdvancedSettingsStore
from app.ai.factory import AiRunnerFactory
from app.config import Settings
from app.git.ai_commit import AiCommitBodyGenerator
from app.git.branch_naming import BranchNamingStrategy
from app.git.service import GitWorktreeService
from app.jobs.diff_review import DiffReviewSummary, build_diff_review_summary
from app.jobs.effective_config import EffectiveConfig
from app.jobs.execution_pipeline import run_job
from app.jobs.fix_pipeline import run_fix_job
from app.jobs.fix_support import (
    compose_fix_source_prompt,
    is_fix_candidate,
    list_fix_candidates,
    resolve_fix_target_job,
)
from app.jobs.heartbeat import HeartbeatHandle
from app.jobs.plan_decisions import PlanDecisionQuestion
from app.jobs.result_notifier import REACTION_QUEUED, ResultNotifier
from app.jobs.result_writer import (
    make_output_summary,
    preserve_partial_output,
    save_runner_log,
    start_incremental_runner_log,
    strip_links_for_stdout_summary,
)
from app.jobs.schemas import FixKind, Job, JobMode, JobRequest
from app.jobs.store import JobStore
from app.jobs.validation import run_validation_command
from app.jobs.worktree_planner import WorktreePlan as _WorktreePlan, prepare_worktree_plan
from app.monitoring.events import EventLogger
from app.projects.registry import ProjectRecord, ProjectRegistry
from app.telegram.notifier import Notifier

_joblog = EventLogger("app.jobs.lifecycle", "job.lifecycle")


class JobManager:
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
        heartbeat_interval_seconds: float = 60,
    ) -> None:
        self._settings = settings
        self._heartbeat_interval_seconds = heartbeat_interval_seconds
        self._job_store = job_store
        self._git_service = git_service
        self._runner_factory = runner_factory
        self._branch_strategy = branch_strategy
        self._notifier_resolver = notifier_resolver
        self._project_registry = project_registry
        self._advanced_settings_store = advanced_settings_store
        self._effective_config = EffectiveConfig(advanced_settings_store)
        self._ai_commit_body_generator = ai_commit_body_generator
        # Set post-construction by the Telegram layer (mirrors command_context.job_manager).
        self.plan_decision_router = plan_decision_router
        self._result_notifier = ResultNotifier(
            notifier_resolver, job_store, heartbeat_interval_seconds
        )
        self._cancel_events: dict[str, threading.Event] = {}
        self._cancelled_job_ids: set[str] = set()
        self._project_locks: dict[str, threading.Lock] = {}
        self._project_locks_guard = threading.Lock()

    def _notifier_for(self, project: str) -> Notifier:
        return self._result_notifier.notifier_for(project)

    def _start_heartbeat(self, job: Job) -> HeartbeatHandle:
        return self._result_notifier.start_heartbeat(job)

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
        return ResultNotifier.message_id_or_none(value)

    @staticmethod
    def _message_ids_or_empty(value: object) -> list[int]:
        return ResultNotifier.message_ids_or_empty(value)

    def _send_result(self, job: Job) -> None:
        self._result_notifier.send_result(job)

    def _react(self, request: JobRequest, emoji: str | None) -> None:
        self._result_notifier.react(request, emoji)

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
        self._react(request, REACTION_QUEUED)
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

    def _build_diff_review(self, job: Job, worktree_path: Path) -> DiffReviewSummary | None:
        # The review card is a reporting aid, so a numstat failure must never fail the job; we log
        # and fall back to no card, leaving the existing changed-files list intact.
        try:
            raw_stats = self._git_service.collect_diff_numstat(worktree_path)
        except RuntimeError as exc:
            _joblog.warning("diff review skipped: %s", exc, **self._job_ctx(job))
            return None
        if not raw_stats:
            return None
        return build_diff_review_summary(raw_stats)

    # Cap the validation command separately from the runner so a hung test suite cannot hold the
    # per-project lock for a second full job timeout on top of the runner's.
    _VALIDATION_TIMEOUT_CAP_SECONDS = 600

    def _run_validation_gate(self, job: Job, entry: ProjectRecord, worktree_path: Path) -> bool:
        # Conservative-commit gate: when the project configures a validation command, run it in the
        # worktree and let the caller commit only if it passes. No command configured means the gate
        # is off and the existing always-commit behavior is preserved.
        command = entry.test_command
        if not command:
            return True
        timeout_seconds = min(
            self._effective_job_timeout_seconds(), self._VALIDATION_TIMEOUT_CAP_SECONDS
        )
        _joblog.info(
            "stage=validation command_set=yes timeout=%d", timeout_seconds, **self._job_ctx(job)
        )
        result = run_validation_command(command, worktree_path, timeout_seconds)
        if result.passed:
            _joblog.info("validation passed", **self._job_ctx(job))
            return True
        job.validation_failed = True
        job.validation_summary = result.output_summary
        _joblog.warning(
            "validation failed exit=%s timed_out=%s; preserving changes uncommitted",
            result.exit_code,
            result.timed_out,
            **self._job_ctx(job),
        )
        return False

    def _prepare_worktree_plan(
        self, job: Job, project_path: Path, worktree_base: Path
    ) -> _WorktreePlan:
        return prepare_worktree_plan(
            job=job,
            project_path=project_path,
            worktree_base=worktree_base,
            git_service=self._git_service,
            job_ctx=self._job_ctx(job),
        )

    def run(self, job_id: str) -> Job:
        job = self._job_store.get(job_id)
        if job is None:
            return run_job(self, job_id)
        with self._project_lock(job.request.project):
            return run_job(self, job_id)

    def recover(self, job_id: str) -> Job:
        job = self._job_store.get(job_id)
        if job is None:
            return run_job(self, job_id)
        with self._project_lock(job.request.project):
            if job.request.mode is JobMode.AGENT_FIX:
                return self._run_fix(job_id)
            return run_job(self, job_id)

    def _project_lock(self, project: str) -> threading.Lock:
        with self._project_locks_guard:
            lock = self._project_locks.get(project)
            if lock is None:
                lock = threading.Lock()
                self._project_locks[project] = lock
            return lock

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
        return is_fix_candidate(job, project, chat_id)

    def list_fix_candidates(self, project: str, chat_id: int, limit: int = 8) -> list[Job]:
        return list_fix_candidates(self._job_store, project, chat_id, limit)

    def resolve_fix_target_job(self, job_id: str, project: str, chat_id: int) -> Job | None:
        return resolve_fix_target_job(self._job_store, job_id, project, chat_id)

    @staticmethod
    def compose_fix_source_prompt(parent_job: Job, fix_instruction: str) -> str:
        return compose_fix_source_prompt(parent_job, fix_instruction)

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
        self._react(request, REACTION_QUEUED)
        with self._project_lock(request.project):
            return self._run_fix(job.id)

    def _run_fix(self, job_id: str) -> Job:
        return run_fix_job(self, job_id)

    @staticmethod
    def _make_job_id() -> str:
        ts = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        return f"job_{ts}_{uuid4().hex[:6]}"

    def _effective_job_timeout_seconds(self) -> int:
        return self._effective_config.job_timeout_seconds()

    def _effective_git_remote_name(self) -> str:
        return self._effective_config.git_remote_name()

    def _effective_keep_worktree_on_success(self) -> bool:
        return self._effective_config.keep_worktree_on_success()

    def _preserve_partial_output(
        self, job: Job, exc: BaseException, worktree_base: Path
    ) -> None:
        preserve_partial_output(job, exc, worktree_base)

    def _save_runner_log(self, job: Job, runner_result, worktree_base: Path) -> None:
        save_runner_log(job, runner_result, worktree_base)

    def _start_incremental_runner_log(self, job: Job, worktree_base: Path):
        return start_incremental_runner_log(job, worktree_base, self._job_store.update)

    @classmethod
    def _strip_links_for_stdout_summary(cls, text: str) -> str:
        return strip_links_for_stdout_summary(text)

    @classmethod
    def _make_output_summary(
        cls,
        text: str,
        limit: int,
        *,
        strip_links: bool = False,
    ) -> str | None:
        return make_output_summary(text, limit=limit, strip_links=strip_links)
