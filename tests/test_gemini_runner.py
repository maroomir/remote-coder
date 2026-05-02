import logging
from pathlib import Path
from unittest.mock import patch

from app.ai.base import RunnerInput
from app.ai.gemini import GeminiRunner


@patch("app.ai.gemini.subprocess.run")
def test_gemini_runner_invokes_subprocess(mock_run, caplog):
    mock_run.return_value.returncode = 0
    mock_run.return_value.stdout = "done"
    mock_run.return_value.stderr = ""
    with caplog.at_level(logging.INFO, logger="app.ai.gemini"):
        runner = GeminiRunner()
        result = runner.run(RunnerInput(instruction="test", cwd=Path("."), timeout_seconds=10))
    assert result.exit_code == 0
    assert result.stdout == "done"
    assert any(r.name == "app.ai.gemini" for r in caplog.records)
    command = mock_run.call_args.args[0]
    assert command == ["gemini", "--approval-mode", "yolo", "-p", "test"]
