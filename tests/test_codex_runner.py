from pathlib import Path
from unittest.mock import patch

from app.ai.base import RunnerInput
from app.ai.codex import CodexRunner
from app.models import CodexSandboxMode


@patch("app.ai.codex.subprocess.run")
def test_codex_runner_invokes_subprocess(mock_run):
    mock_run.return_value.returncode = 0
    mock_run.return_value.stdout = "done"
    mock_run.return_value.stderr = ""
    runner = CodexRunner()
    result = runner.run(RunnerInput(instruction="test", cwd=Path("."), timeout_seconds=10))
    assert result.exit_code == 0
    assert result.stdout == "done"
    command = mock_run.call_args.args[0]
    assert command == ["codex", "exec", "--sandbox", "workspace-write", "test"]


@patch("app.ai.codex.subprocess.run")
def test_codex_runner_respects_sandbox_mode(mock_run):
    mock_run.return_value.returncode = 0
    mock_run.return_value.stdout = ""
    mock_run.return_value.stderr = ""
    CodexRunner(sandbox=CodexSandboxMode.READ_ONLY).run(
        RunnerInput(instruction="x", cwd=Path("."), timeout_seconds=10)
    )
    assert mock_run.call_args.args[0][:4] == ["codex", "exec", "--sandbox", "read-only"]
