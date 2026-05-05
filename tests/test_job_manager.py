import logging
from pathlib import Path
from unittest.mock import Mock

from app.admin.advanced_settings import AdvancedSettings
from app.ai.base import RunnerResult
from app.git.commit_message import CommitMessageFormatter
from app.jobs.manager import JobManager
from app.jobs.schemas import JobRequest
from app.jobs.store import InMemoryJobStore
from app.models import ModelName


def test_job_manager_submit_and_run_success(test_settings, project_registry):
    store = InMemoryJobStore()
    git_service = Mock()
    git_service.prepare_detached_worktree.return_value = Path("/tmp/wt")
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

    manager = JobManager(
        test_settings,
        store,
        git_service,
        factory,
        branch_strategy,
        notifier,
        project_registry,
    )
    request = JobRequest(
        project="remote-coder",
        model=ModelName.CLAUDE,
        instruction="fix bug",
        chat_id=123,
        requested_by=123,
    )
    job = manager.submit(request)
    final_job = manager.run(job.id)

    assert final_job.status.value == "succeeded"
    assert final_job.commit_hash == "abc123"
    assert final_job.branch == "remote-test"
    assert final_job.log_path is not None
    assert final_job.runner_stdout_summary == "ok"
    assert final_job.runner_stderr_summary is None
    git_service.prepare_detached_worktree.assert_called_once()
    git_service.ensure_worktree_writable.assert_called_once_with(Path("/tmp/wt"))
    git_service.create_branch_in_worktree.assert_called_once_with(Path("/tmp/wt"), "remote-test")
    git_service.commit_all.assert_called_once_with(
        Path("/tmp/wt"),
        CommitMessageFormatter.format(job.id, request.instruction, ["a.py"]),
    )
    assert git_service.commit_all.call_args.args[1].endswith(f"committed by remote-coder: {job.id}")
    git_service.push_branch.assert_called_once_with(
        test_settings.project_root, test_settings.git_remote_name, "remote-test"
    )
    call = git_service.prepare_detached_worktree.call_args
    assert call.args[0] == test_settings.project_root
    assert call.kwargs.get("worktree_base_dir") == test_settings.worktree_base_dir
    assert call.kwargs.get("base_branch") is None


def test_job_manager_no_changes_skips_branch_commit_push(test_settings, project_registry):
    store = InMemoryJobStore()
    git_service = Mock()
    git_service.prepare_detached_worktree.return_value = Path("/tmp/wt")
    git_service.collect_changes.return_value = []
    factory = Mock()
    runner = Mock()
    runner.run.return_value = RunnerResult(
        exit_code=0, stdout="ok", stderr="", started_at=None, finished_at=None
    )
    factory.create.return_value = runner
    branch_strategy = Mock()
    notifier = Mock()

    manager = JobManager(
        test_settings,
        store,
        git_service,
        factory,
        branch_strategy,
        notifier,
        project_registry,
    )
    request = JobRequest(
        project="remote-coder",
        model=ModelName.CLAUDE,
        instruction="noop",
        chat_id=123,
        requested_by=123,
    )
    job = manager.submit(request)
    final_job = manager.run(job.id)

    assert final_job.status.value == "succeeded"
    assert final_job.branch is None
    assert final_job.commit_hash is None
    git_service.create_branch_in_worktree.assert_not_called()
    git_service.commit_all.assert_not_called()
    git_service.push_branch.assert_not_called()


def test_job_manager_unknown_project_fails(test_settings, project_registry):
    store = InMemoryJobStore()
    git_service = Mock()
    factory = Mock()
    branch_strategy = Mock()
    notifier = Mock()
    manager = JobManager(
        test_settings,
        store,
        git_service,
        factory,
        branch_strategy,
        notifier,
        project_registry,
    )
    request = JobRequest(
        project="does-not-exist",
        model=ModelName.CLAUDE,
        instruction="x",
        chat_id=1,
        requested_by=1,
    )
    job = manager.submit(request)
    final = manager.run(job.id)
    assert final.status.value == "failed"
    assert final.error_stage == "project_resolve"
    git_service.prepare_detached_worktree.assert_not_called()


def test_job_manager_marks_failed_stage_on_runner_error(test_settings, project_registry):
    store = InMemoryJobStore()
    git_service = Mock()
    git_service.prepare_detached_worktree.return_value = Path("/tmp/wt")
    factory = Mock()
    runner = Mock()
    runner.run.return_value = RunnerResult(
        exit_code=1, stdout="", stderr="runner crashed", started_at=None, finished_at=None
    )
    factory.create.return_value = runner
    branch_strategy = Mock()
    branch_strategy.make_branch_name.return_value = "remote-test"
    notifier = Mock()

    manager = JobManager(
        test_settings,
        store,
        git_service,
        factory,
        branch_strategy,
        notifier,
        project_registry,
    )
    request = JobRequest(
        project="remote-coder",
        model=ModelName.CLAUDE,
        instruction="fix bug",
        chat_id=123,
        requested_by=123,
    )
    job = manager.submit(request)
    final_job = manager.run(job.id)

    assert final_job.status.value == "failed"
    assert final_job.error_stage == "runner"
    assert final_job.runner_stdout_summary is None
    assert final_job.runner_stderr_summary == "runner crashed"


def test_job_manager_push_failure_sets_stage(test_settings, project_registry):
    store = InMemoryJobStore()
    git_service = Mock()
    git_service.prepare_detached_worktree.return_value = Path("/tmp/wt")
    git_service.collect_changes.return_value = ["a.py"]
    git_service.commit_all.return_value = "abc"
    git_service.push_branch.side_effect = RuntimeError("push denied")
    factory = Mock()
    runner = Mock()
    runner.run.return_value = RunnerResult(
        exit_code=0, stdout="ok", stderr="", started_at=None, finished_at=None
    )
    factory.create.return_value = runner
    branch_strategy = Mock()
    branch_strategy.make_branch_name.return_value = "remote-test"
    notifier = Mock()

    manager = JobManager(
        test_settings,
        store,
        git_service,
        factory,
        branch_strategy,
        notifier,
        project_registry,
    )
    request = JobRequest(
        project="remote-coder",
        model=ModelName.CLAUDE,
        instruction="fix bug",
        chat_id=123,
        requested_by=123,
    )
    job = manager.submit(request)
    final_job = manager.run(job.id)

    assert final_job.status.value == "failed"
    assert final_job.error_stage == "git_push"
    assert "push denied" in (final_job.error or "")


def test_job_manager_reuses_existing_branch_worktree(test_settings, project_registry):
    store = InMemoryJobStore()
    git_service = Mock()
    existing_worktree = Path("/tmp/existing-remote-a")
    git_service.local_branch_exists.return_value = True
    git_service.find_linked_worktree_for_branch.return_value = existing_worktree
    git_service.collect_changes.return_value = ["a.py"]
    git_service.commit_all.return_value = "abc123"
    factory = Mock()
    runner = Mock()
    runner.run.return_value = RunnerResult(
        exit_code=0, stdout="ok", stderr="", started_at=None, finished_at=None
    )
    factory.create.return_value = runner
    branch_strategy = Mock()
    notifier = Mock()

    manager = JobManager(
        test_settings,
        store,
        git_service,
        factory,
        branch_strategy,
        notifier,
        project_registry,
    )
    request = JobRequest(
        project="remote-coder",
        model=ModelName.CLAUDE,
        instruction="follow up",
        branch="remote-a",
        chat_id=123,
        requested_by=123,
    )
    job = manager.submit(request)
    final_job = manager.run(job.id)

    assert final_job.status.value == "succeeded"
    assert final_job.branch == "remote-a"
    git_service.prepare_detached_worktree.assert_not_called()
    git_service.prepare_branch_worktree.assert_not_called()
    git_service.create_branch_in_worktree.assert_not_called()
    git_service.ensure_worktree_writable.assert_called_once_with(existing_worktree)
    runner_input = factory.create.return_value.run.call_args.args[0]
    assert runner_input.cwd == existing_worktree


def test_job_manager_truncates_runner_output_summary(test_settings, project_registry):
    store = InMemoryJobStore()
    git_service = Mock()
    git_service.prepare_detached_worktree.return_value = Path("/tmp/wt")
    git_service.collect_changes.return_value = []
    factory = Mock()
    runner = Mock()
    long_stdout = "A" * 13000
    runner.run.return_value = RunnerResult(
        exit_code=0, stdout=long_stdout, stderr="", started_at=None, finished_at=None
    )
    factory.create.return_value = runner
    branch_strategy = Mock()
    notifier = Mock()

    manager = JobManager(
        test_settings,
        store,
        git_service,
        factory,
        branch_strategy,
        notifier,
        project_registry,
    )
    request = JobRequest(
        project="remote-coder",
        model=ModelName.CLAUDE,
        instruction="summarize output",
        chat_id=123,
        requested_by=123,
    )
    job = manager.submit(request)
    final_job = manager.run(job.id)

    assert final_job.status.value == "succeeded"
    assert final_job.runner_stdout_summary is not None
    assert final_job.runner_stdout_summary.endswith("...(truncated)")


def test_job_manager_succeeds_with_no_changes_when_read_only_mentioned_in_output(test_settings, project_registry):
    store = InMemoryJobStore()
    git_service = Mock()
    git_service.prepare_detached_worktree.return_value = Path("/tmp/wt")
    git_service.collect_changes.return_value = []
    factory = Mock()
    runner = Mock()
    runner.run.return_value = RunnerResult(
        exit_code=0,
        stdout="The workspace is read-only so I cannot edit files.",
        stderr="",
        started_at=None,
        finished_at=None,
    )
    factory.create.return_value = runner
    branch_strategy = Mock()
    notifier = Mock()

    manager = JobManager(
        test_settings,
        store,
        git_service,
        factory,
        branch_strategy,
        notifier,
        project_registry,
    )
    request = JobRequest(
        project="remote-coder",
        model=ModelName.CLAUDE,
        instruction="noop",
        chat_id=123,
        requested_by=123,
    )
    job = manager.submit(request)
    final_job = manager.run(job.id)

    assert final_job.status.value == "succeeded"
    assert final_job.branch is None
    assert final_job.commit_hash is None
    assert "read-only" in (final_job.runner_stdout_summary or "").lower()


def test_job_manager_stdout_summary_strips_links():
    raw = "See [guide](https://a.com/b) and https://b.com/c then www.example.org/x tail"
    out = JobManager._make_output_summary(raw, limit=500, strip_links=True)
    assert out
    assert "https://" not in out
    assert "http://" not in out
    assert "www." not in out
    assert "guide" in out
    assert "tail" in out


def test_job_manager_stderr_summary_preserves_urls():
    raw = "error at https://api.example.com/v1"
    out = JobManager._make_output_summary(raw, limit=200, strip_links=False)
    assert out and "https://api.example.com/v1" in out


def test_job_manager_auto_merge_to_main_calls_rebase_after_push(test_settings, project_registry):
    store = InMemoryJobStore()
    git_service = Mock()
    git_service.prepare_detached_worktree.return_value = Path("/tmp/wt")
    git_service.collect_changes.return_value = ["a.py"]
    git_service.commit_all.return_value = "abc123"
    git_service.rebase_branch_onto_main_and_merge.return_value = "rebase ok"
    factory = Mock()
    runner = Mock()
    runner.run.return_value = RunnerResult(
        exit_code=0, stdout="ok", stderr="", started_at=None, finished_at=None
    )
    factory.create.return_value = runner
    branch_strategy = Mock()
    branch_strategy.make_branch_name.return_value = "remote-test"
    notifier = Mock()
    adv_store = Mock()
    adv_store.get.return_value = AdvancedSettings(auto_merge_to_main_enabled=True)

    manager = JobManager(
        test_settings,
        store,
        git_service,
        factory,
        branch_strategy,
        notifier,
        project_registry,
        advanced_settings_store=adv_store,
    )
    request = JobRequest(
        project="remote-coder",
        model=ModelName.CLAUDE,
        instruction="fix bug",
        chat_id=123,
        requested_by=123,
    )
    job = manager.submit(request)
    final_job = manager.run(job.id)

    assert final_job.status.value == "succeeded"
    git_service.rebase_branch_onto_main_and_merge.assert_called_once()
    args, kwargs = git_service.rebase_branch_onto_main_and_merge.call_args
    assert args[0] == test_settings.project_root
    assert args[1] == "remote-test"
    assert args[2] == test_settings.git_remote_name
    assert args[3] == test_settings.worktree_base_dir / "_rebase_ops"


def test_job_manager_auto_merge_failure_sets_integrate_stage(test_settings, project_registry):
    store = InMemoryJobStore()
    git_service = Mock()
    git_service.prepare_detached_worktree.return_value = Path("/tmp/wt")
    git_service.collect_changes.return_value = ["a.py"]
    git_service.commit_all.return_value = "abc123"
    git_service.rebase_branch_onto_main_and_merge.side_effect = RuntimeError("non-ff")
    factory = Mock()
    runner = Mock()
    runner.run.return_value = RunnerResult(
        exit_code=0, stdout="ok", stderr="", started_at=None, finished_at=None
    )
    factory.create.return_value = runner
    branch_strategy = Mock()
    branch_strategy.make_branch_name.return_value = "remote-test"
    notifier = Mock()
    adv_store = Mock()
    adv_store.get.return_value = AdvancedSettings(auto_merge_to_main_enabled=True)

    manager = JobManager(
        test_settings,
        store,
        git_service,
        factory,
        branch_strategy,
        notifier,
        project_registry,
        advanced_settings_store=adv_store,
    )
    request = JobRequest(
        project="remote-coder",
        model=ModelName.CLAUDE,
        instruction="fix bug",
        chat_id=123,
        requested_by=123,
    )
    job = manager.submit(request)
    final_job = manager.run(job.id)

    assert final_job.status.value == "failed"
    assert final_job.error_stage == "git_integrate_main"
    assert "non-ff" in (final_job.error or "")


def test_job_manager_logs_lifecycle_on_success(test_settings, project_registry, caplog):
    store = InMemoryJobStore()
    git_service = Mock()
    git_service.prepare_detached_worktree.return_value = Path("/tmp/wt")
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
    manager = JobManager(
        test_settings,
        store,
        git_service,
        factory,
        branch_strategy,
        notifier,
        project_registry,
    )
    request = JobRequest(
        project="remote-coder",
        model=ModelName.CLAUDE,
        instruction="fix bug",
        chat_id=123,
        requested_by=123,
    )
    with caplog.at_level(logging.INFO, logger="app.jobs.lifecycle"):
        job = manager.submit(request)
        manager.run(job.id)
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "submitted" in joined
    assert "running" in joined
    assert "stage=runner" in joined
    assert "runner exit=0" in joined
    assert "succeeded" in joined


def test_job_manager_logs_exception_on_runner_failure(test_settings, project_registry, caplog):
    store = InMemoryJobStore()
    git_service = Mock()
    git_service.prepare_detached_worktree.return_value = Path("/tmp/wt")
    factory = Mock()
    runner = Mock()
    runner.run.return_value = RunnerResult(
        exit_code=1, stdout="", stderr="runner crashed", started_at=None, finished_at=None
    )
    factory.create.return_value = runner
    branch_strategy = Mock()
    notifier = Mock()
    manager = JobManager(
        test_settings,
        store,
        git_service,
        factory,
        branch_strategy,
        notifier,
        project_registry,
    )
    request = JobRequest(
        project="remote-coder",
        model=ModelName.CLAUDE,
        instruction="fix bug",
        chat_id=123,
        requested_by=123,
    )
    job = manager.submit(request)
    with caplog.at_level(logging.ERROR, logger="app.jobs.lifecycle"):
        manager.run(job.id)
    assert any("failed" in r.getMessage() for r in caplog.records)
