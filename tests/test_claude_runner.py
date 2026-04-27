from pathlib import Path
from unittest.mock import patch

from app.ai.base import RunnerInput
from app.ai.claude import ClaudeRunner


@patch("app.ai.claude.subprocess.run")
def test_claude_runner_invokes_subprocess(mock_run):
    mock_run.return_value.returncode = 0
    mock_run.return_value.stdout = "done"
    mock_run.return_value.stderr = ""
    runner = ClaudeRunner()
    result = runner.run(RunnerInput(instruction="test", cwd=Path("."), timeout_seconds=10))
    assert result.exit_code == 0
    assert result.stdout == "done"
