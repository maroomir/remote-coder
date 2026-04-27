from __future__ import annotations

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
from app.telegram.notifier import TelegramNotifier


class JobManager:
    def __init__(
        self,
        settings: Settings,
        job_store: InMemoryJobStore,
        git_service: GitWorktreeService,
        runner_factory: AiRunnerFactory,
        branch_strategy: BranchNamingStrategy,
        notifier: TelegramNotifier,
    ) -> None:
        self._settings = settings
        self._job_store = job_store
        self._git_service = git_service
        self._runner_factory = runner_factory
        self._branch_strategy = branch_strategy
        self._notifier = notifier

    def submit(self, request: JobRequest) -> Job:
        job = Job(id=self._make_job_id(), request=request)
        self._job_store.create(job)
        self._notifier.send_job_accepted(job)
        return job

    def run(self, job_id: str) -> Job:
        job = self._job_store.get(job_id)
        if not job:
            raise ValueError("job not found")

        project_path = Path(self._settings.project_root)
        worktree_path: Path | None = None
        failed_stage: str | None = None
        try:
            job.mark_running()
            job.branch = job.request.branch or self._branch_strategy.make_branch_name(job.request.instruction)
            self._job_store.update(job)

            failed_stage = "git_worktree"
            worktree_path = self._git_service.prepare_worktree(project_path, job.branch, job.id)
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
            self._save_runner_log(job, runner_result)

            if runner_result.exit_code != 0:
                raise RuntimeError(runner_result.stderr.strip() or "runner failed")

            failed_stage = "git_commit"
            job.changed_files = self._git_service.collect_changes(worktree_path)
            if job.request.commit:
                job.commit_hash = self._git_service.commit_all(worktree_path, f"remote-coder: {job.id}")
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

    def _save_runner_log(self, job: Job, runner_result) -> None:
        log_dir = Path(self._settings.worktree_base_dir) / "_logs"
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
