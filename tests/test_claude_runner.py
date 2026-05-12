import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.ai.base import RunnerInput
from app.ai.claude import ClaudeRunner
from app.jobs.schemas import JobMode


@patch("app.ai.claude.subprocess.Popen")
def test_claude_runner_invokes_subprocess(mock_popen, caplog):
    mock_proc = MagicMock()
    mock_proc.communicate.return_value = ("done", "")
    mock_proc.returncode = 0
    mock_proc.poll.return_value = 0
    mock_popen.return_value = mock_proc
    with caplog.at_level(logging.INFO, logger="app.ai.claude"):
        runner = ClaudeRunner()
        result = runner.run(RunnerInput(instruction="test", cwd=Path("."), timeout_seconds=10))
    assert result.exit_code == 0
    assert result.stdout == "done"
    assert any(r.name == "app.ai.claude" for r in caplog.records)
    cmd = mock_popen.call_args.args[0]
    assert cmd == ["claude", "-p", "test", "--dangerously-skip-permissions"]


@patch("app.ai.claude.subprocess.Popen")
def test_claude_runner_plan_uses_permission_mode_plan(mock_popen, caplog):
    mock_proc = MagicMock()
    mock_proc.communicate.return_value = ("plan out", "")
    mock_proc.returncode = 0
    mock_proc.poll.return_value = 0
    mock_popen.return_value = mock_proc
    with caplog.at_level(logging.INFO, logger="app.ai.claude"):
        runner = ClaudeRunner()
        runner.run(
            RunnerInput(
                instruction="refactor auth",
                cwd=Path("."),
                timeout_seconds=10,
                mode=JobMode.PLAN,
            )
        )
    cmd = mock_popen.call_args.args[0]
    assert cmd[0] == "claude" and cmd[1] == "-p"
    assert "PLAN mode" in cmd[2]
    assert "refactor auth" in cmd[2]
    assert cmd[-2:] == ["--permission-mode", "plan"]
