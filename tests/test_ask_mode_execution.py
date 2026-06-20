"""Characterization tests for ASK read-only mode execution.

PLAN and RESEARCH modes are already exercised through the JobManager in
tests/test_job_manager.py, but ASK was only covered up to the confirmation
button in tests/test_webhook.py. These tests pin the read-only execution
contract (PLAN.md F2/F5-2, .cursor/rules/40 "Job Rules") for ASK: a detached
worktree, no branch, no commit, and no push.
"""

from pathlib import Path
from unittest.mock import Mock

from app.ai.base import RunnerResult
from app.jobs.manager import JobManager
from app.jobs.schemas import JobMode, JobRequest
from app.jobs.store import InMemoryJobStore
from app.models import ModelName


def _build_manager(test_settings, project_registry, git_service, runner):
    factory = Mock()
    factory.create.return_value = runner
    branch_strategy = Mock()
    notifier = Mock()
    return (
        JobManager(
            test_settings,
            InMemoryJobStore(),
            git_service,
            factory,
            branch_strategy,
            lambda _: notifier,
            project_registry,
        ),
        branch_strategy,
    )


def test_job_manager_ask_mode_skips_git_commit_push_and_branch(
    test_settings, project_registry
):
    git_service = Mock()
    git_service.prepare_detached_worktree.return_value = Path("/tmp/wt-ask")
    runner = Mock()
    runner.run.return_value = RunnerResult(
        exit_code=0, stdout="answer text", stderr="", started_at=None, finished_at=None
    )
    manager, branch_strategy = _build_manager(
        test_settings, project_registry, git_service, runner
    )

    # A branch is requested on purpose to prove read-only mode ignores it.
    request = JobRequest(
        project="remote-coder",
        model=ModelName.CLAUDE,
        instruction="explain the JobManager flow",
        mode=JobMode.ASK,
        branch="feature-x",
        chat_id=123,
        requested_by=123,
    )
    job = manager.submit(request)
    final_job = manager.run(job.id)

    assert final_job.status.value == "succeeded"
    assert final_job.branch is None
    assert final_job.commit_hash is None
    assert final_job.changed_files == []

    # Detached worktree from HEAD, never from the requested branch.
    git_service.prepare_detached_worktree.assert_called_once()
    assert git_service.prepare_detached_worktree.call_args.kwargs.get("base_branch") is None
    git_service.local_branch_exists.assert_not_called()

    # No write-side Git work for a read-only ASK job.
    git_service.collect_changes.assert_not_called()
    git_service.create_branch_in_worktree.assert_not_called()
    git_service.commit_all.assert_not_called()
    git_service.push_branch.assert_not_called()
    branch_strategy.make_branch_name.assert_not_called()

    assert runner.run.call_args.args[0].mode == JobMode.ASK
