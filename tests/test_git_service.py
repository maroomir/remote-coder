from pathlib import Path
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
def test_prepare_detached_worktree(mock_run, tmp_path: Path):
    mock_run.return_value.returncode = 0
    mock_run.return_value.stdout = ""
    mock_run.return_value.stderr = ""
    service = GitWorktreeService(base_dir=tmp_path / "wt")
    out = service.prepare_detached_worktree(tmp_path, "job2", worktree_base_dir=tmp_path / "base")
    assert out.name == "job2"
    cmd = mock_run.call_args[0][0]
    assert "worktree" in cmd and "add" in cmd and "--detach" in cmd
    assert cmd[-1] == "HEAD"


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
