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
from app.jobs.execution_pipeline import run_job
from app.jobs.fix_pipeline import run_fix_job
from app.jobs.fix_support import (
    compose_fix_source_prompt,
    is_fix_candidate,
    list_fix_candidates,
    resolve_fix_target_job,
)
from app.jobs.heartbeat import HeartbeatHandle, start_heartbeat
from app.jobs.plan_decisions import PlanDecisionQuestion
from app.jobs.result_writer import (
    make_output_summary,
    preserve_partial_output,
    save_runner_log,
    strip_links_for_stdout_summary,
)
from app.jobs.schemas import FixKind, Job, JobMode, JobRequest
from app.jobs.store import JobStore
from app.jobs.worktree_planner import WorktreePlan as _WorktreePlan, prepare_worktree_plan
from app.monitoring.events import EventLogger
from app.projects.registry import ProjectRegistry
from app.telegram.notifier import Notifier

_joblog = EventLogger("app.jobs.lifecycle", "job.lifecycle")

# Telegram only allows reactions from a fixed allow-list of emoji, so map the job
# lifecycle onto values from https://core.telegram.org/bots/api#reactiontypeemoji.
_REACTION_QUEUED = "👀"
_REACTION_SUCCEEDED = "🎉"
_REACTION_FAILED = "💔"
_REACTION_CANCELLED = "🤝"

_TERMINAL_REACTION_BY_STATUS = {
    "succeeded": _REACTION_SUCCEEDED,
    "failed": _REACTION_FAILED,
    "cancelled": _REACTION_CANCELLED,
}


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
        self._ai_commit_body_generator = ai_commit_body_generator
        # Set post-construction by the Telegram layer (mirrors command_context.job_manager).
        self.plan_decision_router = plan_decision_router
        self._cancel_events: dict[str, threading.Event] = {}
        self._cancelled_job_ids: set[str] = set()
        self._project_locks: dict[str, threading.Lock] = {}
        self._project_locks_guard = threading.Lock()

    def _notifier_for(self, project: str) -> Notifier:
        return self._notifier_resolver(project)

    def _start_heartbeat(self, job: Job) -> HeartbeatHandle:
        return start_heartbeat(
            job=job,
            notifier_resolver=self._notifier_for,
            interval_seconds=self._heartbeat_interval_seconds,
        )

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
        self._react(job.request, _TERMINAL_REACTION_BY_STATUS.get(job.status.value))

    def _react(self, request: JobRequest, emoji: str | None) -> None:
        if request.message_id is None or emoji is None:
            return
        try:
            self._notifier_for(request.project).set_reaction(
                request.chat_id, request.message_id, emoji
            )
        except Exception:  # pylint: disable=broad-except
            _joblog.exception(
                "set_reaction failed",
                chat_id=request.chat_id,
                project=request.project,
            )

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
        self._react(request, _REACTION_QUEUED)
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
        self._react(request, _REACTION_QUEUED)
        with self._project_lock(request.project):
            return self._run_fix(job.id)

    def _run_fix(self, job_id: str) -> Job:
        return run_fix_job(self, job_id)

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

    def _preserve_partial_output(
        self, job: Job, exc: BaseException, worktree_base: Path
    ) -> None:
        preserve_partial_output(job, exc, worktree_base)

    def _save_runner_log(self, job: Job, runner_result, worktree_base: Path) -> None:
        save_runner_log(job, runner_result, worktree_base)

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
