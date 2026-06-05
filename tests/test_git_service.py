import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.git.service import GitWorktreeService


@patch("app.git.service.subprocess.run")
def test_git_service_prepare_worktree(mock_run, tmp_path: Path):
    mock_run.return_value.returncode = 0
    mock_run.return_value.stdout = ""
    mock_run.return_value.stderr = ""
    service = GitWorktreeService(base_dir=tmp_path / "wt")
    result = service.prepare_worktree(tmp_path, "branch", "job1")
    assert result.name == "job1"
    cmd = mock_run.call_args[0][0]
    assert cmd[:4] == ["git", "worktree", "add", "-b"]


@patch("app.git.service.subprocess.run")
def test_prepare_detached_worktree(mock_run, tmp_path: Path, caplog):
    mock_run.return_value.returncode = 0
    mock_run.return_value.stdout = ""
    mock_run.return_value.stderr = ""
    with caplog.at_level(logging.INFO, logger="app.git.service"):
        service = GitWorktreeService(base_dir=tmp_path / "wt")
        out = service.prepare_detached_worktree(tmp_path, "job2", worktree_base_dir=tmp_path / "base")
    assert out.name == "job2"
    cmd = mock_run.call_args[0][0]
    assert "worktree" in cmd and "add" in cmd and "--detach" in cmd
    assert cmd[-1] == "HEAD"
    assert any(r.name == "app.git.service" for r in caplog.records)


@patch("app.git.service.subprocess.run")
def test_prepare_branch_worktree(mock_run, tmp_path: Path):
    mock_run.return_value.returncode = 0
    mock_run.return_value.stdout = ""
    mock_run.return_value.stderr = ""
    service = GitWorktreeService(base_dir=tmp_path / "wt")
    out = service.prepare_branch_worktree(tmp_path, "remote-a", "job3", worktree_base_dir=tmp_path / "base")
    assert out.name == "job3"
    assert mock_run.call_args[0][0] == ["git", "worktree", "add", str(out), "remote-a"]


@patch("app.git.service.subprocess.run")
def test_create_branch_in_worktree(mock_run, tmp_path: Path):
    mock_run.return_value.returncode = 0
    mock_run.return_value.stderr = ""
    service = GitWorktreeService(base_dir=tmp_path)
    service.create_branch_in_worktree(tmp_path / "w", "remote-1")
    mock_run.assert_called_once()
    assert mock_run.call_args[0][0][:4] == ["git", "switch", "-c", "remote-1"]


@patch("app.git.service.subprocess.run")
def test_push_branch(mock_run, tmp_path: Path):
    mock_run.return_value.returncode = 0
    mock_run.return_value.stderr = ""
    service = GitWorktreeService(base_dir=tmp_path)
    service.push_branch(tmp_path, "origin", "remote-x")
    assert mock_run.call_args[0][0] == ["git", "push", "-u", "origin", "remote-x"]


@patch("app.git.service.subprocess.run")
def test_amend_commit_returns_new_short_hash(mock_run, tmp_path: Path):
    mock_run.side_effect = [
        Mock(returncode=0, stdout="", stderr=""),  # git add .
        Mock(returncode=0, stdout="", stderr=""),  # git commit --amend
        Mock(returncode=0, stdout="abc1234\n", stderr=""),  # rev-parse
    ]
    service = GitWorktreeService(base_dir=tmp_path)
    result = service.amend_commit(tmp_path / "wt", "fix: refreshed message")
    assert result == "abc1234"
    amend_call = mock_run.call_args_list[1][0][0]
    assert amend_call[:3] == ["git", "commit", "--amend"]
    assert "--allow-empty" in amend_call
    assert "-m" in amend_call
    assert "fix: refreshed message" in amend_call


@patch("app.git.service.subprocess.run")
def test_push_branch_force_with_lease_uses_lease_flag(mock_run, tmp_path: Path):
    mock_run.return_value.returncode = 0
    mock_run.return_value.stdout = ""
    mock_run.return_value.stderr = ""
    service = GitWorktreeService(base_dir=tmp_path)
    service.push_branch_force_with_lease(tmp_path, "origin", "remote-x")
    assert mock_run.call_args[0][0] == [
        "git",
        "push",
        "--force-with-lease",
        "origin",
        "remote-x",
    ]


@patch("app.git.service.subprocess.run")
def test_push_branch_force_with_lease_raises_with_git_stderr(mock_run, tmp_path: Path):
    mock_run.return_value.returncode = 1
    mock_run.return_value.stdout = ""
    mock_run.return_value.stderr = "stale info: remote ref has changed"
    service = GitWorktreeService(base_dir=tmp_path)
    try:
        service.push_branch_force_with_lease(tmp_path, "origin", "remote-x")
    except RuntimeError as exc:
        assert "stale info" in str(exc)
        assert "--force-with-lease" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


@patch("app.git.service.subprocess.run")
def test_resolve_integrate_branch_prefers_main(mock_run, tmp_path: Path):
    mock_run.return_value.returncode = 0
    mock_run.return_value.stdout = ""
    mock_run.return_value.stderr = ""
    service = GitWorktreeService(base_dir=tmp_path)
    assert service.resolve_integrate_branch(tmp_path) == "main"
    assert mock_run.call_args[0][0] == ["git", "rev-parse", "--verify", "main"]


@patch("app.git.service.subprocess.run")
def test_format_local_branches(mock_run, tmp_path: Path):
    mock_run.return_value.returncode = 0
    mock_run.return_value.stdout = "* main\n"
    mock_run.return_value.stderr = ""
    service = GitWorktreeService(base_dir=tmp_path)
    assert service.format_local_branches(tmp_path).strip() == "* main"
    cmd = mock_run.call_args[0][0]
    assert cmd[:2] == ["git", "branch"]
    assert "--sort=refname" in cmd


@patch("app.git.service.subprocess.run")
def test_list_local_branches_strips_markers(mock_run, tmp_path: Path):
    mock_run.return_value.returncode = 0
    mock_run.return_value.stdout = "* main\n+ feature/a\n  release\n"
    mock_run.return_value.stderr = ""
    service = GitWorktreeService(base_dir=tmp_path)

    assert service.list_local_branches(tmp_path) == ["feature/a", "main", "release"]
    cmd = mock_run.call_args[0][0]
    assert cmd[:2] == ["git", "branch"]
    assert "--sort=refname" in cmd


@patch("app.git.service.subprocess.run")
def test_count_local_branches(mock_run, tmp_path: Path):
    mock_run.return_value.returncode = 0
    mock_run.return_value.stdout = "main\nfeature\n"
    mock_run.return_value.stderr = ""
    service = GitWorktreeService(base_dir=tmp_path)
    assert service.count_local_branches(tmp_path) == 2
    assert mock_run.call_args[0][0][:3] == ["git", "branch", "--format=%(refname:short)"]


@patch("app.git.service.subprocess.run")
def test_count_remote_branches_for_remote(mock_run, tmp_path: Path):
    mock_run.return_value.returncode = 0
    mock_run.return_value.stdout = (
        "  origin/HEAD -> origin/main\n"
        "  origin/main\n"
        "  origin/foo\n"
    )
    mock_run.return_value.stderr = ""
    service = GitWorktreeService(base_dir=tmp_path)
    assert service.count_remote_branches_for_remote(tmp_path, "origin") == 2


@patch("app.git.service.subprocess.run")
def test_list_worktree_entries(mock_run, tmp_path: Path):
    sample = (
        "worktree /repo\n"
        "HEAD abc\n"
        "branch refs/heads/main\n"
        "\n"
        "worktree /repo/wt\n"
        "HEAD def\n"
        "detached\n"
    )
    mock_run.return_value.returncode = 0
    mock_run.return_value.stdout = sample
    mock_run.return_value.stderr = ""
    service = GitWorktreeService(base_dir=tmp_path)
    entries = service.list_worktree_entries(tmp_path)
    assert len(entries) == 2
    assert entries[0][1] == "main"
    assert entries[1][1] is None


@patch("app.git.service.subprocess.run")
def test_format_remote_branches_for_remote_filters_head(mock_run, tmp_path: Path):
    mock_run.return_value.returncode = 0
    mock_run.return_value.stdout = (
        "  origin/HEAD -> origin/main\n"
        "  origin/main\n"
        "  other/xyz\n"
    )
    mock_run.return_value.stderr = ""
    service = GitWorktreeService(base_dir=tmp_path)
    out = service.format_remote_branches_for_remote(tmp_path, "origin")
    assert "origin/main" in out
    assert "other/" not in out
    assert "HEAD" not in out


@patch("app.git.service.subprocess.run")
def test_get_current_branch(mock_run, tmp_path: Path):
    mock_run.return_value.returncode = 0
    mock_run.return_value.stdout = "feature\n"
    mock_run.return_value.stderr = ""
    service = GitWorktreeService(base_dir=tmp_path)
    assert service.get_current_branch(tmp_path) == "feature"


@patch("app.git.service.subprocess.run")
def test_get_current_branch_detached(mock_run, tmp_path: Path):
    mock_run.return_value.returncode = 0
    mock_run.return_value.stdout = "\n"
    mock_run.return_value.stderr = ""
    service = GitWorktreeService(base_dir=tmp_path)
    assert "detached" in service.get_current_branch(tmp_path)


@patch("app.git.service.subprocess.run")
def test_local_branch_exists_true(mock_run, tmp_path: Path):
    mock_run.return_value.returncode = 0
    mock_run.return_value.stderr = ""
    service = GitWorktreeService(base_dir=tmp_path)
    assert service.local_branch_exists(tmp_path, "main") is True


@patch("app.git.service.subprocess.run")
def test_local_branch_exists_false(mock_run, tmp_path: Path):
    mock_run.return_value.returncode = 1
    mock_run.return_value.stderr = "unknown ref"
    service = GitWorktreeService(base_dir=tmp_path)
    assert service.local_branch_exists(tmp_path, "missing") is False


@patch("app.git.service.subprocess.run")
def test_switch_branch_runs_git_switch(mock_run, tmp_path: Path):
    mock_run.side_effect = [
        Mock(returncode=0, stderr=""),
        Mock(returncode=0, stderr=""),
    ]
    service = GitWorktreeService(base_dir=tmp_path)
    service.switch_branch(tmp_path, "develop")
    assert mock_run.call_count == 2
    assert mock_run.call_args_list[1][0][0] == ["git", "switch", "develop"]


def test_ensure_worktree_writable_succeeds_on_writable_dir(tmp_path: Path):
    d = tmp_path / "wt_probe"
    d.mkdir(parents=True)
    GitWorktreeService.ensure_worktree_writable(d)


@patch("app.git.service.subprocess.run")
def test_list_remote_branches_matching_uses_ls_remote(mock_run, tmp_path: Path):
    mock_run.return_value.returncode = 0
    mock_run.return_value.stderr = ""
    mock_run.return_value.stdout = (
        "abc123\trefs/heads/remote-x\n"
        "def456\trefs/heads/remote-feature/foo\n"
        "111111\trefs/heads/main\n"
    )
    service = GitWorktreeService(base_dir=tmp_path)
    out = service.list_remote_branches_matching(tmp_path, "origin", "remote-")
    assert out == ["remote-feature/foo", "remote-x"]
    cmd = mock_run.call_args[0][0]
    assert cmd == ["git", "ls-remote", "--heads", "origin"]


@patch("app.git.service.subprocess.run")
def test_list_remote_branches_matching_empty_when_no_hits(mock_run, tmp_path: Path):
    mock_run.return_value.returncode = 0
    mock_run.return_value.stderr = ""
    mock_run.return_value.stdout = ""
    service = GitWorktreeService(base_dir=tmp_path)
    assert service.list_remote_branches_matching(tmp_path, "origin", "remote-") == []


@patch("app.git.service.subprocess.run")
def test_list_local_branches_matching_strips_plus_worktree_marker(mock_run, tmp_path: Path):
    mock_run.return_value.returncode = 0
    mock_run.return_value.stderr = ""
    mock_run.return_value.stdout = (
        "* main\n"
        "+ remote-task-20260428-151253\n"
        "+ remote-ai-1-20260428-214810\n"
    )
    service = GitWorktreeService(base_dir=tmp_path)
    out = service.list_local_branches_matching(tmp_path, "remote-")
    assert out == ["remote-ai-1-20260428-214810", "remote-task-20260428-151253"]


def test_parse_worktree_list_porcelain_extracts_paths_and_branches():
    sample = (
        "worktree /repo\n"
        "HEAD abc\n"
        "branch refs/heads/main\n"
        "\n"
        "worktree /repo/wt1\n"
        "HEAD def\n"
        "branch refs/heads/remote-task-20260428-151253\n"
        "\n"
        "worktree /repo/wt2\n"
        "HEAD ghi\n"
        "detached\n"
    )
    parsed = GitWorktreeService._parse_worktree_list_porcelain(sample)
    assert len(parsed) == 3
    assert parsed[0][1] == "main"
    assert parsed[1][1] == "remote-task-20260428-151253"
    assert parsed[2][1] is None


@patch("app.git.service.subprocess.run")
def test_find_linked_worktree_for_branch_ignores_root(mock_run, tmp_path: Path):
    mock_run.return_value.returncode = 0
    mock_run.return_value.stderr = ""
    root = tmp_path / "repo"
    root.mkdir()
    other = tmp_path / "repo-wt"
    mock_run.return_value.stdout = (
        f"worktree {root}\n"
        "HEAD abc\n"
        "branch refs/heads/remote-a\n"
        "\n"
        f"worktree {other}\n"
        "HEAD def\n"
        "branch refs/heads/remote-a\n"
    )
    service = GitWorktreeService(base_dir=tmp_path)
    assert service.find_linked_worktree_for_branch(root, "remote-a") == other


@patch("app.git.service.subprocess.run")
def test_branch_is_checked_out_includes_root_worktree(mock_run, tmp_path: Path):
    mock_run.return_value.returncode = 0
    mock_run.return_value.stderr = ""
    root = tmp_path / "repo"
    mock_run.return_value.stdout = (
        f"worktree {root}\n"
        "HEAD abc\n"
        "branch refs/heads/main\n"
    )

    service = GitWorktreeService(base_dir=tmp_path)
    assert service.branch_is_checked_out(root, "main") is True


@patch("app.git.service.subprocess.run")
def test_list_remote_branches_matching_raises_on_failure(mock_run, tmp_path: Path):
    mock_run.return_value.returncode = 1
    mock_run.return_value.stderr = "connection refused"
    mock_run.return_value.stdout = ""
    service = GitWorktreeService(base_dir=tmp_path)
    try:
        service.list_remote_branches_matching(tmp_path, "origin", "remote-")
    except RuntimeError as exc:
        assert "failed to list remote branches" in str(exc)
        assert "connection refused" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


@patch("app.git.service.subprocess.run")
def test_cleanup_managed_worktrees_removes_managed_and_remote_branch_entries(mock_run, tmp_path: Path):
    project_path = tmp_path / "repo"
    project_path.mkdir()
    worktree_base = tmp_path / "worktrees"
    worktree_base.mkdir()
    managed_detached = worktree_base / "job-1"
    remote_branch_wt = tmp_path / "other-remote"
    untouched = tmp_path / "manual"
    root = project_path.resolve()
    porcelain = (
        f"worktree {root}\n"
        "HEAD abc\n"
        "branch refs/heads/main\n"
        "\n"
        f"worktree {managed_detached}\n"
        "HEAD def\n"
        "detached\n"
        "\n"
        f"worktree {remote_branch_wt}\n"
        "HEAD 123\n"
        "branch refs/heads/remote-cleanup\n"
        "\n"
        f"worktree {untouched}\n"
        "HEAD 999\n"
        "branch refs/heads/feature-keep\n"
    )
    commands: list[list[str]] = []

    def fake_run(argv: list[str], **_kwargs):
        commands.append(list(argv))
        if argv[:4] == ["git", "worktree", "list", "--porcelain"]:
            return Mock(returncode=0, stdout=porcelain, stderr="")
        if argv[:3] == ["git", "worktree", "remove"]:
            return Mock(returncode=0, stdout="", stderr="")
        if argv[:3] == ["git", "worktree", "prune"]:
            return Mock(returncode=0, stdout="", stderr="")
        raise AssertionError(f"unexpected git argv: {argv}")

    mock_run.side_effect = fake_run
    service = GitWorktreeService(base_dir=worktree_base)
    removed = service.cleanup_managed_worktrees(project_path, worktree_base, branch_prefix="remote-")

    assert removed == 2
    removed_targets = [c[-1] for c in commands if c[:3] == ["git", "worktree", "remove"]]
    assert str(managed_detached.resolve()) in removed_targets
    assert str(remote_branch_wt.resolve()) in removed_targets
    assert str(untouched.resolve()) not in removed_targets
    assert any(c[:3] == ["git", "worktree", "prune"] for c in commands)


@patch("app.git.service.subprocess.run")
def test_cleanup_managed_worktrees_raises_when_prune_fails(mock_run, tmp_path: Path):
    project_path = tmp_path / "repo"
    project_path.mkdir()
    worktree_base = tmp_path / "worktrees"
    worktree_base.mkdir()
    root = project_path.resolve()
    porcelain = (
        f"worktree {root}\n"
        "HEAD abc\n"
        "branch refs/heads/main\n"
    )
    commands: list[list[str]] = []

    def fake_run(argv: list[str], **_kwargs):
        commands.append(list(argv))
        if argv[:4] == ["git", "worktree", "list", "--porcelain"]:
            return Mock(returncode=0, stdout=porcelain, stderr="")
        if argv[:3] == ["git", "worktree", "prune"]:
            return Mock(returncode=1, stdout="", stderr="prune failed")
        raise AssertionError(f"unexpected git argv: {argv}")

    mock_run.side_effect = fake_run
    service = GitWorktreeService(base_dir=worktree_base)
    try:
        service.cleanup_managed_worktrees(project_path, worktree_base)
    except RuntimeError as exc:
        assert "failed to prune worktrees" in str(exc)
        assert "prune failed" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


@patch("app.git.service.uuid.uuid4", return_value=SimpleNamespace(hex="aaaaaaaa1234567890abcdef12345678"))
@patch("app.git.service.subprocess.run")
def test_rebase_branch_onto_main_removes_linked_worktree_before_add(mock_run, _mock_uuid, tmp_path: Path):
    project_path = tmp_path / "repo"
    project_path.mkdir()
    linked = tmp_path / "job_wt"
    linked.mkdir()
    root = project_path.resolve()
    branch = "feature-rebase-wt"
    porcelain = (
        f"worktree {root}\n"
        "HEAD abcdefabcdefabcdefabcdefabcdefabcdef\n"
        "branch refs/heads/main\n"
        "\n"
        f"worktree {linked.resolve()}\n"
        "HEAD fedcbafedcbafedcbafedcbafedcbafedcbafedc\n"
        f"branch refs/heads/{branch}\n"
    )
    commands: list[list[str]] = []

    def fake_run(argv: list[str], **_kwargs):
        commands.append(list(argv))
        cmd = argv
        stdout = ""
        stderr = ""
        rc = 0
        if cmd[:4] == ["git", "rev-parse", "--verify", "main"]:
            stdout = "deadbeef\n"
        elif cmd[:2] == ["git", "fetch"]:
            pass
        elif cmd[:4] == ["git", "worktree", "list", "--porcelain"]:
            stdout = porcelain
        elif cmd[:3] == ["git", "worktree", "remove"]:
            # linked job worktree 제거 후, finally에서 rebase 임시 worktree 제거
            target = cmd[-1]
            assert target == str(linked.resolve()) or "_rebase_aaaaaaaa" in target
        elif cmd[:3] == ["git", "worktree", "add"]:
            assert "-B" in cmd
            assert branch in cmd
        elif cmd[:2] == ["git", "rebase"]:
            pass
        elif cmd[:2] == ["git", "push"]:
            pass
        elif cmd[:2] == ["git", "checkout"]:
            pass
        elif cmd[:2] == ["git", "pull"]:
            pass
        elif cmd[:2] == ["git", "merge"]:
            pass
        else:
            raise AssertionError(f"unexpected git argv: {cmd}")
        return Mock(returncode=rc, stdout=stdout, stderr=stderr)

    mock_run.side_effect = fake_run
    service = GitWorktreeService(base_dir=tmp_path)
    ops = tmp_path / "rebase_ops"
    summary = service.rebase_branch_onto_main_and_merge(project_path, branch, "origin", ops)

    assert "rebase 완료" in summary
    idx_list = next(i for i, c in enumerate(commands) if c[1:4] == ["worktree", "list", "--porcelain"])
    idx_remove_linked = next(
        i for i, c in enumerate(commands) if c[1:3] == ["worktree", "remove"] and c[-1] == str(linked.resolve())
    )
    idx_add = next(i for i, c in enumerate(commands) if c[1:3] == ["worktree", "add"] and "-B" in c)
    assert idx_list < idx_remove_linked < idx_add
