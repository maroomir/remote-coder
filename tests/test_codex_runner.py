import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.ai.base import RunnerInput
from app.ai.codex import CodexRunner
from app.models import CodexSandboxMode


@patch("app.ai.codex.subprocess.Popen")
def test_codex_runner_invokes_subprocess(mock_popen, caplog):
    mock_proc = MagicMock()
    mock_proc.communicate.return_value = ("done", "")
    mock_proc.returncode = 0
    mock_proc.poll.return_value = 0
    mock_popen.return_value = mock_proc
    with caplog.at_level(logging.INFO, logger="app.ai.codex"):
        runner = CodexRunner()
        result = runner.run(RunnerInput(instruction="test", cwd=Path("."), timeout_seconds=10))
    assert result.exit_code == 0
    assert result.stdout == "done"
    assert any(r.name == "app.ai.codex" for r in caplog.records)
    command = mock_popen.call_args.args[0]
    assert command == ["codex", "exec", "--sandbox", "workspace-write", "test"]


@patch("app.ai.codex.subprocess.Popen")
def test_codex_runner_respects_sandbox_mode(mock_popen, caplog):
    mock_proc = MagicMock()
    mock_proc.communicate.return_value = ("", "")
    mock_proc.returncode = 0
    mock_proc.poll.return_value = 0
    mock_popen.return_value = mock_proc
    with caplog.at_level(logging.INFO, logger="app.ai.codex"):
        CodexRunner(sandbox=CodexSandboxMode.READ_ONLY).run(
            RunnerInput(instruction="x", cwd=Path("."), timeout_seconds=10)
        )
    assert mock_popen.call_args.args[0][:4] == ["codex", "exec", "--sandbox", "read-only"]
