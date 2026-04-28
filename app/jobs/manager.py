from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.ai.base import RunnerInput
from app.ai.factory import AiRunnerFactory
from app.config import Settings
from app.git.branch_naming import BranchNamingStrategy
from app.git.service import GitWorktreeService
from app.jobs.schemas import Job, JobRequest
from app.jobs.store import InMemoryJobStore
from app.projects.registry import ProjectRegistry
from app.telegram.notifier import TelegramNotifier


class JobManager:
    _ANSI_ESCAPE_PATTERN = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
    _STDOUT_SUMMARY_LIMIT = 1200
    _STDERR_SUMMARY_LIMIT = 800

    def __init__(
        self,
        settings: Settings,
        job_store: InMemoryJobStore,
        git_service: GitWorktreeService,
        runner_factory: AiRunnerFactory,
        branch_strategy: BranchNamingStrategy,
        notifier: TelegramNotifier,
        project_registry: ProjectRegistry,
    ) -> None:
        self._settings = settings
        self._job_store = job_store
        self._git_service = git_service
        self._runner_factory = runner_factory
        self._branch_strategy = branch_strategy
        self._notifier = notifier
        self._project_registry = project_registry

    def submit(self, request: JobRequest) -> Job:
        job = Job(id=self._make_job_id(), request=request)
        self._job_store.create(job)
        self._notifier.send_job_accepted(job)
        return job

    def run(self, job_id: str) -> Job:
        job = self._job_store.get(job_id)
        if not job:
            raise ValueError("job not found")

        entry = self._project_registry.get(job.request.project)
        if not entry or not entry.enabled:
            job.mark_failed("unknown or disabled project")
            job.error_stage = "project_resolve"
            self._job_store.update(job)
            self._notifier.send_job_result(job)
            return job

        project_path = entry.root_path
        worktree_base = entry.worktree_base_dir
        worktree_path: Path | None = None
        failed_stage: str | None = None
        remote = self._settings.git_remote_name
        try:
            job.mark_running()
            self._job_store.update(job)

            failed_stage = "git_worktree"
            worktree_path = self._git_service.prepare_detached_worktree(
                project_path,
                job.id,
                worktree_base_dir=worktree_base,
            )

            failed_stage = "runner"
            runner = self._runner_factory.create(job.request.model)
            runner_result = runner.run(
                RunnerInput(
                    instruction=job.request.instruction,
                    cwd=worktree_path,
                    timeout_seconds=self._settings.job_timeout_seconds,
                    env=None,
                )
            )
            self._save_runner_log(job, runner_result, worktree_base)

            if runner_result.exit_code != 0:
                raise RuntimeError(runner_result.stderr.strip() or "runner failed")

            failed_stage = "git_commit"
            job.changed_files = self._git_service.collect_changes(worktree_path)

            if not job.changed_files:
                job.branch = None
                job.commit_hash = None
                job.mark_succeeded()
                self._job_store.update(job)
            else:
                job.branch = job.request.branch or self._branch_strategy.make_branch_name(job.request.instruction)
                self._job_store.update(job)
                self._git_service.create_branch_in_worktree(worktree_path, job.branch)
                job.changed_files = self._git_service.collect_changes(worktree_path)

                if job.request.commit:
                    job.commit_hash = self._git_service.commit_all(
                        worktree_path, f"remote-coder: {job.id}"
                    )
                else:
                    job.commit_hash = None

                if job.request.commit and job.commit_hash:
                    failed_stage = "git_push"
                    self._git_service.push_branch(project_path, remote, job.branch)

                job.mark_succeeded()
                self._job_store.update(job)
        except Exception as exc:  # pylint: disable=broad-except
            job.mark_failed(str(exc))
            job.error_stage = failed_stage or "unknown"
            self._job_store.update(job)
        finally:
            if (
                worktree_path
                and job.status.value == "succeeded"
                and not self._settings.keep_worktree_on_success
            ):
                self._git_service.cleanup_worktree(project_path, worktree_path)
            self._notifier.send_job_result(job)
        return job

    @staticmethod
    def _make_job_id() -> str:
        ts = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        return f"job_{ts}_{uuid4().hex[:6]}"

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
            runner_result.stdout, limit=self._STDOUT_SUMMARY_LIMIT
        )
        job.runner_stderr_summary = self._make_output_summary(
            runner_result.stderr, limit=self._STDERR_SUMMARY_LIMIT
        )

    @classmethod
    def _make_output_summary(cls, text: str, limit: int) -> str | None:
        if not text:
            return None
        no_ansi = cls._ANSI_ESCAPE_PATTERN.sub("", text)
        normalized = "\n".join(line.rstrip() for line in no_ansi.splitlines()).strip()
        if not normalized:
            return None
        if len(normalized) <= limit:
            return normalized
        return f"{normalized[:limit].rstrip()}...(truncated)"
