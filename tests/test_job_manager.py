import logging
from pathlib import Path
from unittest.mock import Mock

from app.admin.advanced_settings import AdvancedSettings
from app.ai.base import RunnerResult
from app.git.commit_message import CommitMessageFormatter
from app.jobs.manager import JobManager
from app.jobs.schemas import JobMode, JobRequest
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
        lambda _: notifier,
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


def test_job_store_keeps_multiple_runs_for_reused_job_id(test_settings, project_registry):
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
        lambda _: notifier,
        project_registry,
    )
    first = manager.submit(
        JobRequest(
            project="remote-coder",
            model=ModelName.CLAUDE,
            instruction="first",
            chat_id=123,
            requested_by=123,
        )
    )
    second = manager.submit(
        JobRequest(
            project="remote-coder",
            model=ModelName.CLAUDE,
            instruction="second",
            chat_id=123,
            requested_by=123,
            job_id=first.id,
        )
    )

    assert second.id == first.id
    assert store.get(first.id) is second
    assert [job.request.instruction for job in store.list_recent(10)[:2]] == ["second", "first"]


def test_job_manager_extracts_runner_usage(test_settings, project_registry):
    store = InMemoryJobStore()
    git_service = Mock()
    git_service.prepare_detached_worktree.return_value = Path("/tmp/wt")
    git_service.collect_changes.return_value = []
    factory = Mock()
    runner = Mock()
    runner.run.return_value = RunnerResult(
        exit_code=0,
        stdout="model: ChatGPT 5.5\ninput tokens: 1,200\noutput tokens: 300",
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
        lambda _: notifier,
        project_registry,
    )
    request = JobRequest(
        project="remote-coder",
        model=ModelName.CODEX,
        instruction="report usage",
        chat_id=123,
        requested_by=123,
    )
    job = manager.submit(request)
    final_job = manager.run(job.id)

    assert final_job.status.value == "succeeded"
    assert final_job.runner_actual_model == "ChatGPT 5.5"
    assert final_job.runner_token_usage == {"input": 1200, "output": 300}


def test_job_manager_uses_advanced_job_timeout(test_settings, project_registry):
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
    adv_store = Mock()
    adv_store.get.return_value = AdvancedSettings(job_timeout_seconds=3600)

    manager = JobManager(
        test_settings,
        store,
        git_service,
        factory,
        branch_strategy,
        lambda _: notifier,
        project_registry,
        advanced_settings_store=adv_store,
    )
    request = JobRequest(
        project="remote-coder",
        model=ModelName.CLAUDE,
        instruction="long task",
        chat_id=123,
        requested_by=123,
    )
    job = manager.submit(request)
    manager.run(job.id)

    runner_input = runner.run.call_args.args[0]
    assert runner_input.timeout_seconds == 3600


def test_job_manager_plan_mode_skips_git_commit_push_and_branch(test_settings, project_registry):
    store = InMemoryJobStore()
    git_service = Mock()
    git_service.prepare_detached_worktree.return_value = Path("/tmp/wt-plan")
    factory = Mock()
    runner = Mock()
    runner.run.return_value = RunnerResult(
        exit_code=0, stdout="plan text", stderr="", started_at=None, finished_at=None
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
        lambda _: notifier,
        project_registry,
    )
    request = JobRequest(
        project="remote-coder",
        model=ModelName.CLAUDE,
        instruction="outline steps",
        mode=JobMode.PLAN,
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
    git_service.prepare_detached_worktree.assert_called_once()
    assert git_service.prepare_detached_worktree.call_args.kwargs.get("base_branch") is None
    git_service.local_branch_exists.assert_not_called()
    git_service.collect_changes.assert_not_called()
    git_service.create_branch_in_worktree.assert_not_called()
    git_service.commit_all.assert_not_called()
    git_service.push_branch.assert_not_called()
    branch_strategy.make_branch_name.assert_not_called()
    assert runner.run.call_args.args[0].mode == JobMode.PLAN


def test_job_manager_plan_success_cleans_worktree_despite_keep_flag(test_settings, project_registry):
    store = InMemoryJobStore()
    git_service = Mock()
    git_service.prepare_detached_worktree.return_value = Path("/tmp/wt-plan2")
    factory = Mock()
    runner = Mock()
    runner.run.return_value = RunnerResult(
        exit_code=0, stdout="ok", stderr="", started_at=None, finished_at=None
    )
    factory.create.return_value = runner
    branch_strategy = Mock()
    notifier = Mock()
    assert test_settings.keep_worktree_on_success is True

    manager = JobManager(
        test_settings,
        store,
        git_service,
        factory,
        branch_strategy,
        lambda _: notifier,
        project_registry,
    )
    request = JobRequest(
        project="remote-coder",
        model=ModelName.CLAUDE,
        instruction="plan only",
        mode=JobMode.PLAN,
        chat_id=123,
        requested_by=123,
    )
    job = manager.submit(request)
    manager.run(job.id)

    git_service.cleanup_worktree.assert_called_once_with(test_settings.project_root, Path("/tmp/wt-plan2"))


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
        lambda _: notifier,
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
        lambda _: notifier,
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
        lambda _: notifier,
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
        lambda _: notifier,
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
        lambda _: notifier,
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


def test_job_manager_uses_detached_worktree_when_requested_branch_is_checked_out(
    test_settings,
    project_registry,
):
    store = InMemoryJobStore()
    git_service = Mock()
    git_service.local_branch_exists.return_value = True
    git_service.find_linked_worktree_for_branch.return_value = None
    git_service.branch_is_checked_out.return_value = True
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
        lambda _: notifier,
        project_registry,
    )
    request = JobRequest(
        project="remote-coder",
        model=ModelName.CLAUDE,
        instruction="fix bug",
        branch="main",
        chat_id=123,
        requested_by=123,
    )
    job = manager.submit(request)
    final_job = manager.run(job.id)

    assert final_job.status.value == "succeeded"
    assert final_job.branch == "remote-test"
    git_service.prepare_branch_worktree.assert_not_called()
    git_service.prepare_detached_worktree.assert_called_once_with(
        test_settings.project_root,
        job.id,
        worktree_base_dir=test_settings.worktree_base_dir,
        base_branch="main",
    )
    git_service.create_branch_in_worktree.assert_called_once_with(Path("/tmp/wt"), "remote-test")


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
        lambda _: notifier,
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
        lambda _: notifier,
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
        lambda _: notifier,
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
        lambda _: notifier,
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
        lambda _: notifier,
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
        lambda _: notifier,
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


def test_job_manager_notifier_resolver_invoked_with_job_project(test_settings, project_registry):
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
    resolved: list[str] = []

    def resolver(project: str):
        resolved.append(project)
        return notifier

    manager = JobManager(
        test_settings,
        store,
        git_service,
        factory,
        branch_strategy,
        resolver,
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
    manager.run(job.id)

    assert resolved == ["remote-coder", "remote-coder"]
    notifier.send_job_accepted.assert_called_once()
    notifier.send_job_result.assert_called_once()


def test_job_manager_forwards_selected_model_to_ai_commit_generator(test_settings, project_registry):
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
    ai_commit = Mock()
    ai_commit.generate.return_value = (None, None)

    manager = JobManager(
        test_settings,
        store,
        git_service,
        factory,
        branch_strategy,
        lambda _: notifier,
        project_registry,
        ai_commit_body_generator=ai_commit,
    )
    request = JobRequest(
        project="remote-coder",
        model=ModelName.CODEX,
        instruction="apply codex fix",
        chat_id=123,
        requested_by=123,
    )
    job = manager.submit(request)
    manager.run(job.id)

    ai_commit.generate.assert_called_once()
    assert ai_commit.generate.call_args.kwargs["model_name"] == ModelName.CODEX


def test_job_manager_routes_notifications_by_project_name(test_settings, project_registry):
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
    notifier_primary = Mock()
    notifier_other = Mock()

    def resolver(project: str):
        return notifier_primary if project == "remote-coder" else notifier_other

    manager = JobManager(
        test_settings,
        store,
        git_service,
        factory,
        branch_strategy,
        resolver,
        project_registry,
    )
    job = manager.submit(
        JobRequest(
            project="remote-coder",
            model=ModelName.CLAUDE,
            instruction="noop",
            chat_id=1,
            requested_by=1,
        )
    )
    manager.run(job.id)

    notifier_primary.send_job_accepted.assert_called_once()
    notifier_primary.send_job_result.assert_called_once()
    notifier_other.send_job_accepted.assert_not_called()
    notifier_other.send_job_result.assert_not_called()


# ---- /fix manager tests ---------------------------------------------------


def _seed_parent_job(store, *, project="remote-coder", chat_id=1, branch="remote-fix-1", commit="abc1234"):
    from app.jobs.schemas import Job, JobStatus

    parent = Job(
        id="parent_job",
        request=JobRequest(
            project=project,
            model=ModelName.CLAUDE,
            instruction="original work",
            chat_id=chat_id,
            requested_by=chat_id,
        ),
        status=JobStatus.SUCCEEDED,
        branch=branch,
        commit_hash=commit,
        changed_files=["a.py"],
    )
    store.create(parent)
    return parent


def test_execute_fix_job_commit_uses_prepared_message_and_force_lease(
    test_settings, project_registry
):
    from app.jobs.schemas import FixKind, JobMode

    store = InMemoryJobStore()
    parent = _seed_parent_job(store)
    git_service = Mock()
    git_service.find_linked_worktree_for_branch.return_value = None
    git_service.prepare_branch_worktree.return_value = Path("/tmp/wt-fix")
    git_service.amend_commit.return_value = "def5678"
    factory = Mock()
    branch_strategy = Mock()
    notifier = Mock()
    notifier.send_job_accepted.return_value = 99
    notifier.send_job_result.return_value = [100]

    manager = JobManager(
        test_settings,
        store,
        git_service,
        factory,
        branch_strategy,
        lambda _: notifier,
        project_registry,
    )
    request = JobRequest(
        project="remote-coder",
        model=ModelName.CLAUDE,
        instruction="ignored",
        chat_id=1,
        requested_by=1,
        mode=JobMode.AGENT_FIX,
        fix_kind=FixKind.COMMIT,
        parent_job_id=parent.id,
        branch=parent.branch,
    )
    prepared = (
        f"feat: refreshed\n\n- bullet\n\ncommitted by remote-coder: {parent.id}"
    )
    final = manager.execute_fix_job(request, prepared_message=prepared)

    assert final.status.value == "succeeded"
    assert final.commit_hash == "def5678"
    assert final.branch == parent.branch
    git_service.amend_commit.assert_called_once_with(Path("/tmp/wt-fix"), prepared)
    git_service.push_branch_force_with_lease.assert_called_once_with(
        test_settings.project_root, test_settings.git_remote_name, parent.branch
    )
    # Runner should not be invoked for commit-only mode
    factory.create.assert_not_called()
    # Parent job is preserved unchanged
    refreshed_parent = store.get(parent.id)
    assert refreshed_parent.commit_hash == "abc1234"


def test_execute_fix_job_source_runs_runner_and_amends(test_settings, project_registry):
    from app.ai.base import RunnerResult
    from app.jobs.schemas import FixKind, JobMode

    store = InMemoryJobStore()
    parent = _seed_parent_job(store)
    git_service = Mock()
    git_service.find_linked_worktree_for_branch.return_value = Path("/tmp/wt-existing")
    git_service.collect_changes.return_value = ["b.py"]
    git_service.amend_commit.return_value = "new1234"
    runner = Mock()
    runner.run.return_value = RunnerResult(
        exit_code=0, stdout="ok", stderr="", started_at=None, finished_at=None
    )
    factory = Mock()
    factory.create.return_value = runner
    branch_strategy = Mock()
    notifier = Mock()

    manager = JobManager(
        test_settings,
        store,
        git_service,
        factory,
        branch_strategy,
        lambda _: notifier,
        project_registry,
    )
    request = JobRequest(
        project="remote-coder",
        model=ModelName.CLAUDE,
        instruction="rename foo to bar",
        chat_id=1,
        requested_by=1,
        mode=JobMode.AGENT_FIX,
        fix_kind=FixKind.SOURCE,
        parent_job_id=parent.id,
        branch=parent.branch,
    )
    final = manager.execute_fix_job(request)

    assert final.status.value == "succeeded"
    assert final.commit_hash == "new1234"
    assert final.branch == parent.branch
    # changed files merged
    assert "a.py" in final.changed_files and "b.py" in final.changed_files
    runner.run.assert_called_once()
    runner_input = runner.run.call_args.args[0]
    assert "사용자 후속 수정 요청" in runner_input.instruction
    assert "rename foo to bar" in runner_input.instruction
    assert "original work" in runner_input.instruction
    # commit message trailer keeps parent id
    amend_call = git_service.amend_commit.call_args
    assert amend_call.args[0] == Path("/tmp/wt-existing")
    assert amend_call.args[1].endswith(f"committed by remote-coder: {parent.id}")
    git_service.push_branch_force_with_lease.assert_called_once()
    # Existing linked worktree reused, no prepare
    git_service.prepare_branch_worktree.assert_not_called()


def test_execute_fix_job_source_no_diff_skips_push(test_settings, project_registry):
    from app.ai.base import RunnerResult
    from app.jobs.schemas import FixKind, JobMode

    store = InMemoryJobStore()
    parent = _seed_parent_job(store)
    git_service = Mock()
    git_service.find_linked_worktree_for_branch.return_value = Path("/tmp/wt")
    git_service.collect_changes.return_value = []
    runner = Mock()
    runner.run.return_value = RunnerResult(
        exit_code=0, stdout="no-op", stderr="", started_at=None, finished_at=None
    )
    factory = Mock()
    factory.create.return_value = runner
    branch_strategy = Mock()
    notifier = Mock()

    manager = JobManager(
        test_settings,
        store,
        git_service,
        factory,
        branch_strategy,
        lambda _: notifier,
        project_registry,
    )
    final = manager.execute_fix_job(
        JobRequest(
            project="remote-coder",
            model=ModelName.CLAUDE,
            instruction="nothing",
            chat_id=1,
            requested_by=1,
            mode=JobMode.AGENT_FIX,
            fix_kind=FixKind.SOURCE,
            parent_job_id=parent.id,
            branch=parent.branch,
        )
    )

    assert final.status.value == "succeeded"
    assert final.branch == parent.branch
    assert final.commit_hash == parent.commit_hash
    git_service.amend_commit.assert_not_called()
    git_service.push_branch_force_with_lease.assert_not_called()


def test_execute_fix_job_rejects_failed_parent(test_settings, project_registry):
    from app.jobs.schemas import FixKind, Job, JobMode, JobStatus

    store = InMemoryJobStore()
    failed_parent = Job(
        id="parent_failed",
        request=JobRequest(
            project="remote-coder",
            model=ModelName.CLAUDE,
            instruction="x",
            chat_id=1,
            requested_by=1,
        ),
        status=JobStatus.FAILED,
    )
    store.create(failed_parent)

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
        lambda _: notifier,
        project_registry,
    )
    final = manager.execute_fix_job(
        JobRequest(
            project="remote-coder",
            model=ModelName.CLAUDE,
            instruction="anything",
            chat_id=1,
            requested_by=1,
            mode=JobMode.AGENT_FIX,
            fix_kind=FixKind.COMMIT,
            parent_job_id=failed_parent.id,
        ),
        prepared_message="msg",
    )

    assert final.status.value == "failed"
    assert final.error_stage == "fix_resolve_target"


def test_list_fix_candidates_only_includes_succeeded_with_branch_and_commit(
    test_settings, project_registry
):
    from app.jobs.schemas import Job, JobStatus

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
        lambda _: notifier,
        project_registry,
    )
    succeeded = Job(
        id="ok",
        request=JobRequest(
            project="remote-coder",
            model=ModelName.CLAUDE,
            instruction="x",
            chat_id=7,
            requested_by=7,
        ),
        status=JobStatus.SUCCEEDED,
        branch="remote-a",
        commit_hash="abc",
    )
    no_branch = Job(
        id="no_branch",
        request=JobRequest(
            project="remote-coder",
            model=ModelName.CLAUDE,
            instruction="x",
            chat_id=7,
            requested_by=7,
        ),
        status=JobStatus.SUCCEEDED,
        branch=None,
        commit_hash="abc",
    )
    no_commit = Job(
        id="no_commit",
        request=JobRequest(
            project="remote-coder",
            model=ModelName.CLAUDE,
            instruction="x",
            chat_id=7,
            requested_by=7,
        ),
        status=JobStatus.SUCCEEDED,
        branch="remote-b",
        commit_hash=None,
    )
    other_chat = Job(
        id="other_chat",
        request=JobRequest(
            project="remote-coder",
            model=ModelName.CLAUDE,
            instruction="x",
            chat_id=99,
            requested_by=99,
        ),
        status=JobStatus.SUCCEEDED,
        branch="remote-c",
        commit_hash="abc",
    )
    for job in (succeeded, no_branch, no_commit, other_chat):
        store.create(job)
    candidates = manager.list_fix_candidates("remote-coder", 7, limit=10)
    candidate_ids = {job.id for job in candidates}
    assert candidate_ids == {"ok"}
