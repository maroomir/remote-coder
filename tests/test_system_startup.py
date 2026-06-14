from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.jobs.schemas import Job, JobRequest, JobStatus
from app.jobs.store import InMemoryJobStore
from app.monitoring.events import EventLogger
from app.models import ModelName
from app.system_startup import (
    SERVER_RESTART_ERROR,
    SERVER_RESTART_STAGE,
    recover_startup_jobs,
    run_startup_project_pulls,
)


@pytest.fixture
def mock_git():
    m = MagicMock()
    m.pull_repository.return_value = "ok summary"
    return m


def test_run_startup_project_pulls_skipped_when_disabled(mock_git):
    registry = MagicMock()
    log = MagicMock(spec=EventLogger)
    run_startup_project_pulls(
        pull_projects_on_server_startup_enabled=False,
        project_registry=registry,
        git_service=mock_git,
        remote="origin",
        system_log=log,
    )
    registry.list_projects.assert_not_called()
    mock_git.pull_repository.assert_not_called()


def test_run_startup_project_pulls_dedupes_paths(mock_git):
    root = Path("/same/repo").resolve()
    r1 = SimpleNamespace(enabled=True, name="proj_a", root_path=root)
    r2 = SimpleNamespace(enabled=True, name="proj_b", root_path=root)
    registry = MagicMock()
    registry.list_projects.return_value = [r1, r2]
    log = MagicMock(spec=EventLogger)
    run_startup_project_pulls(
        pull_projects_on_server_startup_enabled=True,
        project_registry=registry,
        git_service=mock_git,
        remote="upstream",
        system_log=log,
    )
    mock_git.pull_repository.assert_called_once()
    assert mock_git.pull_repository.call_args[0][0] == root
    assert mock_git.pull_repository.call_args[0][1] == "upstream"


def test_run_startup_project_pulls_skips_disabled_records(mock_git, tmp_path):
    disabled = SimpleNamespace(enabled=False, name="x", root_path=tmp_path / "x")
    enabled = SimpleNamespace(enabled=True, name="y", root_path=tmp_path / "y")
    registry = MagicMock()
    registry.list_projects.return_value = [disabled, enabled]
    log = MagicMock(spec=EventLogger)
    run_startup_project_pulls(
        pull_projects_on_server_startup_enabled=True,
        project_registry=registry,
        git_service=mock_git,
        remote="origin",
        system_log=log,
    )
    mock_git.pull_repository.assert_called_once()
    assert mock_git.pull_repository.call_args[0][0] == (tmp_path / "y").resolve()


def test_run_startup_project_pulls_logs_exception_and_continues(mock_git, tmp_path):
    r = SimpleNamespace(enabled=True, name="z", root_path=tmp_path)
    registry = MagicMock()
    registry.list_projects.return_value = [r]
    mock_git.pull_repository.side_effect = RuntimeError("pull failed")
    log = MagicMock(spec=EventLogger)
    run_startup_project_pulls(
        pull_projects_on_server_startup_enabled=True,
        project_registry=registry,
        git_service=mock_git,
        remote="origin",
        system_log=log,
    )
    log.exception.assert_called_once_with("startup pull failed", project="z")


def test_recover_startup_jobs_marks_running_failed_without_notification():
    store = InMemoryJobStore()
    running = Job(
        id="running-job",
        request=JobRequest(
            project="p",
            model=ModelName.CLAUDE,
            instruction="x",
            chat_id=1,
            requested_by=1,
        ),
        status=JobStatus.RUNNING,
    )
    store.create(running)
    run_job = MagicMock()
    record = MagicMock()
    log = MagicMock(spec=EventLogger)

    thread = recover_startup_jobs(
        job_store=store,
        run_job=run_job,
        record_final_job_result=record,
        system_log=log,
    )

    recovered = store.get("running-job")
    assert thread is None
    assert recovered is not None
    assert recovered.status is JobStatus.FAILED
    assert recovered.error == SERVER_RESTART_ERROR
    assert recovered.error_stage == SERVER_RESTART_STAGE
    run_job.assert_not_called()
    record.assert_not_called()


def test_recover_startup_jobs_reruns_queued_jobs_and_records_result():
    store = InMemoryJobStore()
    queued = Job(
        id="queued-job",
        request=JobRequest(
            project="p",
            model=ModelName.CLAUDE,
            instruction="x",
            chat_id=1,
            requested_by=1,
        ),
        status=JobStatus.QUEUED,
    )
    store.create(queued)
    log = MagicMock(spec=EventLogger)
    recorded: list[str] = []

    def run_job(job_id: str) -> Job:
        job = store.get(job_id)
        assert job is not None
        job.mark_running()
        job.mark_succeeded()
        store.update(job)
        return job

    thread = recover_startup_jobs(
        job_store=store,
        run_job=run_job,
        record_final_job_result=lambda job: recorded.append(job.id),
        system_log=log,
    )

    assert thread is not None
    thread.join(timeout=1)
    assert not thread.is_alive()
    assert store.get("queued-job").status is JobStatus.SUCCEEDED
    assert recorded == ["queued-job"]
