from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.monitoring.events import EventLogger
from app.system_startup import run_startup_project_pulls


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
