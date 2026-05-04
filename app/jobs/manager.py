from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.admin.advanced_settings import FileAdvancedSettingsStore
from app.ai.base import RunnerInput
from app.ai.factory import AiRunnerFactory
from app.config import Settings
from app.git.ai_commit import AiCommitBodyGenerator
from app.git.branch_naming import BranchNamingStrategy
from app.git.commit_message import CommitMessageFormatter
from app.git.service import GitWorktreeService
from app.jobs.schemas import Job, JobRequest
from app.jobs.store import InMemoryJobStore
from app.monitoring.events import EventLogger
from app.projects.registry import ProjectRegistry
from app.telegram.notifier import TelegramNotifier

_joblog = EventLogger("app.jobs.lifecycle", "job.lifecycle")


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
        job_store: InMemoryJobStore,
        git_service: GitWorktreeService,
        runner_factory: AiRunnerFactory,
        branch_strategy: BranchNamingStrategy,
        notifier: TelegramNotifier,
        project_registry: ProjectRegistry,
        advanced_settings_store: FileAdvancedSettingsStore | None = None,
        ai_commit_body_generator: AiCommitBodyGenerator | None = None,
    ) -> None:
        self._settings = settings
        self._job_store = job_store
        self._git_service = git_service
        self._runner_factory = runner_factory
        self._branch_strategy = branch_strategy
        self._notifier = notifier
        self._project_registry = project_registry
        self._advanced_settings_store = advanced_settings_store
        self._ai_commit_body_generator = ai_commit_body_generator

    def submit(self, request: JobRequest) -> Job:
        job = Job(id=self._make_job_id(), request=request)
        self._job_store.create(job)
        _joblog.info(
            "submitted model=%s",
            request.model.value,
            chat_id=request.chat_id,
            user_id=request.requested_by,
            project=request.project,
            job_id=job.id,
        )
        self._notifier.send_job_accepted(job)
        return job

    def run(self, job_id: str) -> Job:
        job = self._job_store.get(job_id)
        if not job:
            raise ValueError("job not found")

        entry = self._project_registry.get(job.request.project)
        if not entry or not entry.enabled:
            _joblog.warning(
                "unknown/disabled project",
                chat_id=job.request.chat_id,
                user_id=job.request.requested_by,
                project=job.request.project,
                job_id=job.id,
            )
            job.mark_failed("unknown or disabled project")
            job.error_stage = "project_resolve"
            self._job_store.update(job)
            self._notifier.send_job_result(job)
            return job

        project_path = entry.root_path
        worktree_base = entry.worktree_base_dir
        worktree_path: Path | None = None
        created_worktree_for_job = False
        failed_stage: str | None = None
        remote = self._settings.git_remote_name
        try:
            job.mark_running()
            self._job_store.update(job)
            _joblog.info(
                "running",
                chat_id=job.request.chat_id,
                user_id=job.request.requested_by,
                project=job.request.project,
                job_id=job.id,
            )

            failed_stage = "git_worktree"
            _joblog.info(
                "stage=git_worktree",
                chat_id=job.request.chat_id,
                user_id=job.request.requested_by,
                project=job.request.project,
                job_id=job.id,
            )
            worktree_on_branch = False
            requested_branch = job.request.branch
            if requested_branch and self._git_service.local_branch_exists(project_path, requested_branch):
                existing_worktree = self._git_service.find_linked_worktree_for_branch(
                    project_path,
                    requested_branch,
                )
                if existing_worktree is not None:
                    worktree_path = existing_worktree
                else:
                    worktree_path = self._git_service.prepare_branch_worktree(
                        project_path,
                        requested_branch,
                        job.id,
                        worktree_base_dir=worktree_base,
                    )
                    created_worktree_for_job = True
                worktree_on_branch = True
            else:
                worktree_path = self._git_service.prepare_detached_worktree(
                    project_path,
                    job.id,
                    worktree_base_dir=worktree_base,
                )
                created_worktree_for_job = True
            self._git_service.ensure_worktree_writable(worktree_path)

            failed_stage = "runner"
            _joblog.info(
                "stage=runner model=%s",
                job.request.model.value,
                chat_id=job.request.chat_id,
                user_id=job.request.requested_by,
                project=job.request.project,
                job_id=job.id,
            )
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
            _joblog.info(
                "runner exit=%d",
                runner_result.exit_code,
                chat_id=job.request.chat_id,
                user_id=job.request.requested_by,
                project=job.request.project,
                job_id=job.id,
            )

            if runner_result.exit_code != 0:
                raise RuntimeError(runner_result.stderr.strip() or "runner failed")

            failed_stage = "git_commit"
            _joblog.info(
                "stage=git_commit",
                chat_id=job.request.chat_id,
                user_id=job.request.requested_by,
                project=job.request.project,
                job_id=job.id,
            )
            job.changed_files = self._git_service.collect_changes(worktree_path)
            _joblog.info(
                "changes=%d",
                len(job.changed_files),
                chat_id=job.request.chat_id,
                user_id=job.request.requested_by,
                project=job.request.project,
                job_id=job.id,
            )

            if not job.changed_files:
                job.branch = None
                job.commit_hash = None
                job.mark_succeeded()
                self._job_store.update(job)
                _joblog.info(
                    "succeeded branch=%s commit=%s",
                    "-",
                    "-",
                    chat_id=job.request.chat_id,
                    user_id=job.request.requested_by,
                    project=job.request.project,
                    job_id=job.id,
                )
            else:
                job.branch = job.request.branch or self._branch_strategy.make_branch_name(job.request.instruction)
                self._job_store.update(job)
                if not worktree_on_branch:
                    self._git_service.create_branch_in_worktree(worktree_path, job.branch)
                    worktree_on_branch = True
                job.changed_files = self._git_service.collect_changes(worktree_path)

                if job.request.commit:
                    ai_body = None
                    if self._ai_commit_body_generator is not None:
                        ai_body = self._ai_commit_body_generator.generate(
                            instruction=job.request.instruction,
                            changed_files=job.changed_files,
                        )
                    commit_message = CommitMessageFormatter.format(
                        job_id=job.id,
                        instruction=job.request.instruction,
                        changed_files=job.changed_files,
                        ai_body=ai_body,
                    )
                    job.commit_hash = self._git_service.commit_all(worktree_path, commit_message)
                else:
                    job.commit_hash = None

                if job.request.commit and job.commit_hash:
                    failed_stage = "git_push"
                    _joblog.info(
                        "stage=git_push",
                        chat_id=job.request.chat_id,
                        user_id=job.request.requested_by,
                        project=job.request.project,
                        job_id=job.id,
                    )
                    self._git_service.push_branch(project_path, remote, job.branch)

                if (
                    self._advanced_settings_store is not None
                    and self._advanced_settings_store.get().auto_merge_to_main_enabled
                    and job.request.commit
                    and job.commit_hash
                    and job.branch
                ):
                    failed_stage = "git_integrate_main"
                    _joblog.info(
                        "stage=git_integrate_main",
                        chat_id=job.request.chat_id,
                        user_id=job.request.requested_by,
                        project=job.request.project,
                        job_id=job.id,
                    )
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
                    chat_id=job.request.chat_id,
                    user_id=job.request.requested_by,
                    project=job.request.project,
                    job_id=job.id,
                )
        except Exception as exc:  # pylint: disable=broad-except
            _joblog.exception(
                "failed stage=%s: %s",
                failed_stage or "unknown",
                exc,
                chat_id=job.request.chat_id,
                user_id=job.request.requested_by,
                project=job.request.project,
                job_id=job.id,
            )
            job.mark_failed(str(exc))
            job.error_stage = failed_stage or "unknown"
            self._job_store.update(job)
        finally:
            if (
                worktree_path
                and created_worktree_for_job
                and job.status.value == "succeeded"
                and not self._settings.keep_worktree_on_success
            ):
                try:
                    self._git_service.cleanup_worktree(project_path, worktree_path)
                except RuntimeError:
                    # cleanup 실패로 성공 Job 알림이 누락되지 않도록 삼킵니다.
                    pass
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
            runner_result.stdout,
            limit=self._STDOUT_SUMMARY_LIMIT,
            strip_links=True,
        )
        job.runner_stderr_summary = self._make_output_summary(
            runner_result.stderr, limit=self._STDERR_SUMMARY_LIMIT
        )

    @classmethod
    def _strip_links_for_stdout_summary(cls, text: str) -> str:
        """텔레그램 요약에 넣기 전 stdout에서 URL·Markdown 링크를 제거합니다."""
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
