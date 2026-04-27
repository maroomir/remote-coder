from pathlib import Path
from unittest.mock import Mock

from app.ai.base import RunnerResult
from app.jobs.manager import JobManager
from app.jobs.schemas import JobRequest
from app.jobs.store import InMemoryJobStore
from app.models import ModelName


def test_job_manager_submit_and_run_success(test_settings):
    store = InMemoryJobStore()
    git_service = Mock()
    git_service.prepare_worktree.return_value = Path("/tmp/wt")
    git_service.collect_changes.return_value = ["a.py"]
    git_service.commit_all.return_value = "abc123"
    factory = Mock()
    runner = Mock()
    runner.run.return_value = RunnerResult(
        exit_code=0, stdout="ok", stderr="", started_at=None, finished_at=None
    )
    factory.create.return_value = runner
    branch_strategy = Mock()
    branch_strategy.make_branch_name.return_value = "remote-test"
    notifier = Mock()

    manager = JobManager(test_settings, store, git_service, factory, branch_strategy, notifier)
    request = JobRequest(
        project="proj",
        model=ModelName.CLAUDE,
        instruction="fix bug",
        chat_id=123,
        requested_by=123,
    )
    job = manager.submit(request)
    final_job = manager.run(job.id)

    assert final_job.status.value == "succeeded"
    assert final_job.commit_hash == "abc123"
