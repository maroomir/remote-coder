import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.ai.base import RunnerInput
from app.ai.gemini import GeminiRunner


@patch("app.ai.gemini.subprocess.Popen")
def test_gemini_runner_invokes_subprocess(mock_popen, caplog):
    mock_proc = MagicMock()
    mock_proc.communicate.return_value = ("done", "")
    mock_proc.returncode = 0
    mock_proc.poll.return_value = 0
    mock_popen.return_value = mock_proc
    with caplog.at_level(logging.INFO, logger="app.ai.gemini"):
        runner = GeminiRunner()
        result = runner.run(RunnerInput(instruction="test", cwd=Path("."), timeout_seconds=10))
    assert result.exit_code == 0
    assert result.stdout == "done"
    assert any(r.name == "app.ai.gemini" for r in caplog.records)
    command = mock_popen.call_args.args[0]
    assert command == ["gemini", "--approval-mode", "yolo", "-p", "test"]
