from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from pydantic import SecretStr

from app.ai.base import RunnerResult
from app.jobs.manager import JobManager
from app.jobs.schemas import JobRequest
from app.jobs.store import InMemoryJobStore
from app.jobs.validation import ValidationResult
from app.models import ModelName
from app.projects.registry import ProjectRecord, ProjectRegistry


@pytest.fixture
def gated_registry(isolate_remote_coder_home: Path, tmp_path: Path) -> ProjectRegistry:
    path = isolate_remote_coder_home / "gated-registry.json"
    reg = ProjectRegistry(path)
    root = tmp_path / "repo"
    root.mkdir(parents=True, exist_ok=True)
    reg.add_project(
        ProjectRecord(
            name="remote-coder",
            root_path=root,
            default_model=ModelName.CLAUDE,
            enabled=True,
            bot_token=SecretStr("token"),
            allowed_chat_ids=[123],
            test_command="pytest -q",
        )
    )
    return reg


def _manager(test_settings, registry, git_service, store=None) -> JobManager:
    factory = Mock()
    runner = Mock()
    runner.run.return_value = RunnerResult(
        exit_code=0, stdout="ok", stderr="", started_at=None, finished_at=None
    )
    factory.create.return_value = runner
    branch_strategy = Mock()
    branch_strategy.make_branch_name.return_value = "remote-test"
    return JobManager(
        test_settings,
        store if store is not None else InMemoryJobStore(),
        git_service,
        factory,
        branch_strategy,
        lambda _: Mock(),
        registry,
    )


def _request() -> JobRequest:
    return JobRequest(
        project="remote-coder",
        model=ModelName.CLAUDE,
        instruction="fix bug",
        chat_id=123,
        requested_by=123,
    )


def test_gate_passes_commits_as_usual(test_settings, gated_registry):
    git_service = Mock()
    git_service.prepare_detached_worktree.return_value = Path("/tmp/wt")
    git_service.collect_changes.return_value = ["a.py"]
    git_service.collect_diff_numstat.return_value = []
    git_service.commit_all.return_value = "abc123"
    manager = _manager(test_settings, gated_registry, git_service)

    with patch(
        "app.jobs.manager.run_validation_command",
        return_value=ValidationResult(passed=True, exit_code=0, output_summary="ok"),
    ) as mock_validate:
        job = manager.submit(_request())
        final = manager.run(job.id)

    mock_validate.assert_called_once()
    assert final.status.value == "succeeded"
    assert final.commit_hash == "abc123"
    assert final.validation_failed is False
    git_service.commit_all.assert_called_once()
    git_service.push_branch.assert_called_once()


def test_gate_fails_skips_commit_and_preserves_changes(test_settings, gated_registry):
    git_service = Mock()
    git_service.prepare_detached_worktree.return_value = Path("/tmp/wt")
    git_service.collect_changes.return_value = ["a.py"]
    git_service.collect_diff_numstat.return_value = []
    manager = _manager(test_settings, gated_registry, git_service)

    with patch(
        "app.jobs.manager.run_validation_command",
        return_value=ValidationResult(
            passed=False, exit_code=1, output_summary="1 failed"
        ),
    ):
        job = manager.submit(_request())
        final = manager.run(job.id)

    assert final.status.value == "succeeded"
    assert final.validation_failed is True
    assert final.validation_summary == "1 failed"
    assert final.commit_hash is None
    git_service.commit_all.assert_not_called()
    git_service.push_branch.assert_not_called()
    # Worktree is preserved for inspection, not cleaned up.
    git_service.cleanup_worktree.assert_not_called()


def test_gate_off_when_no_test_command(test_settings, project_registry):
    git_service = Mock()
    git_service.prepare_detached_worktree.return_value = Path("/tmp/wt")
    git_service.collect_changes.return_value = ["a.py"]
    git_service.collect_diff_numstat.return_value = []
    git_service.commit_all.return_value = "abc123"
    manager = _manager(test_settings, project_registry, git_service)

    with patch("app.jobs.manager.run_validation_command") as mock_validate:
        job = manager.submit(_request())
        final = manager.run(job.id)

    mock_validate.assert_not_called()
    assert final.commit_hash == "abc123"
    assert final.validation_failed is False


def test_gate_skipped_when_commit_is_false(test_settings, gated_registry):
    git_service = Mock()
    git_service.prepare_detached_worktree.return_value = Path("/tmp/wt")
    git_service.collect_changes.return_value = ["a.py"]
    git_service.collect_diff_numstat.return_value = []
    manager = _manager(test_settings, gated_registry, git_service)

    request = JobRequest(
        project="remote-coder",
        model=ModelName.CLAUDE,
        instruction="just look, do not commit",
        chat_id=123,
        requested_by=123,
        commit=False,
    )
    with patch("app.jobs.manager.run_validation_command") as mock_validate:
        job = manager.submit(request)
        final = manager.run(job.id)

    # A no-commit request must not trigger the gate or spuriously flag a failure.
    mock_validate.assert_not_called()
    assert final.validation_failed is False
    assert final.commit_hash is None
    git_service.commit_all.assert_not_called()


def _seed_parent_job(store):
    from app.jobs.schemas import Job, JobStatus

    parent = Job(
        id="parent_job",
        request=JobRequest(
            project="remote-coder",
            model=ModelName.CLAUDE,
            instruction="original work",
            chat_id=123,
            requested_by=123,
        ),
        status=JobStatus.SUCCEEDED,
        branch="remote-fix-1",
        commit_hash="abc1234",
        changed_files=["a.py"],
    )
    store.create(parent)
    return parent


def _fix_request(parent):
    from app.jobs.schemas import FixKind, JobMode

    return JobRequest(
        project="remote-coder",
        model=ModelName.CLAUDE,
        instruction="repair it",
        chat_id=123,
        requested_by=123,
        mode=JobMode.AGENT_FIX,
        fix_kind=FixKind.SOURCE,
        parent_job_id=parent.id,
        branch=parent.branch,
    )


def test_fix_gate_fails_keeps_parent_commit_and_preserves_changes(test_settings, gated_registry):
    store = InMemoryJobStore()
    parent = _seed_parent_job(store)
    git_service = Mock()
    git_service.find_linked_worktree_for_branch.return_value = Path("/tmp/wt-existing")
    git_service.collect_changes.return_value = ["b.py"]
    git_service.collect_diff_numstat.return_value = [("b.py", 5, 1)]
    manager = _manager(test_settings, gated_registry, git_service, store=store)

    with patch(
        "app.jobs.manager.run_validation_command",
        return_value=ValidationResult(passed=False, exit_code=1, output_summary="fix failed"),
    ):
        final = manager.execute_fix_job(_fix_request(parent))

    assert final.status.value == "succeeded"
    assert final.validation_failed is True
    assert final.validation_summary == "fix failed"
    # The review card is still built on the validation-failure path (matches execution_pipeline).
    assert final.diff_review is not None
    assert final.diff_review.file_count == 1
    # Parent commit untouched; no amend or force-push happened.
    assert final.commit_hash == parent.commit_hash
    git_service.amend_commit.assert_not_called()
    git_service.push_branch_force_with_lease.assert_not_called()
    git_service.cleanup_worktree.assert_not_called()


def test_fix_gate_passes_amends_and_pushes(test_settings, gated_registry):
    store = InMemoryJobStore()
    parent = _seed_parent_job(store)
    git_service = Mock()
    git_service.find_linked_worktree_for_branch.return_value = Path("/tmp/wt-existing")
    git_service.collect_changes.return_value = ["b.py"]
    git_service.collect_diff_numstat.return_value = []
    git_service.amend_commit.return_value = "new1234"
    manager = _manager(test_settings, gated_registry, git_service, store=store)

    with patch(
        "app.jobs.manager.run_validation_command",
        return_value=ValidationResult(passed=True, exit_code=0, output_summary="ok"),
    ):
        final = manager.execute_fix_job(_fix_request(parent))

    assert final.status.value == "succeeded"
    assert final.validation_failed is False
    assert final.commit_hash == "new1234"
    git_service.amend_commit.assert_called_once()
    git_service.push_branch_force_with_lease.assert_called_once()
