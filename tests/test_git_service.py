from pathlib import Path
from unittest.mock import patch

from app.git.service import GitWorktreeService


@patch("app.git.service.subprocess.run")
def test_git_service_prepare_worktree(mock_run, tmp_path: Path):
    mock_run.return_value.returncode = 0
    mock_run.return_value.stdout = ""
    mock_run.return_value.stderr = ""
    service = GitWorktreeService(base_dir=tmp_path / "wt")
    result = service.prepare_worktree(tmp_path, "branch", "job1")
    assert result.name == "job1"
