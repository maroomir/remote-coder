import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.ai.base import RunnerInput
from app.ai.gemini import GeminiRunner
from app.jobs.schemas import JobMode


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
    assert command == ["gemini", "--approval-mode", "yolo", "--skip-trust", "-p", "test"]


@patch("app.ai.gemini.subprocess.Popen")
def test_gemini_runner_plan_mode_skips_yolo_flags(mock_popen, caplog):
    mock_proc = MagicMock()
    mock_proc.communicate.return_value = ("answer", "")
    mock_proc.returncode = 0
    mock_proc.poll.return_value = 0
    mock_popen.return_value = mock_proc
    with caplog.at_level(logging.INFO, logger="app.ai.gemini"):
        GeminiRunner().run(
            RunnerInput(
                instruction="what is X",
                cwd=Path("."),
                timeout_seconds=10,
                mode=JobMode.ASK,
            )
        )
    command = mock_popen.call_args.args[0]
    assert command[0] == "gemini"
    assert "--skip-trust" in command
    assert "-p" in command
    prompt_arg = command[command.index("-p") + 1]
    assert "ASK mode" in prompt_arg
    assert "what is X" in prompt_arg
    assert "--approval-mode" not in command


@patch("app.ai.gemini.subprocess.Popen")
def test_gemini_runner_passes_model_id(mock_popen):
    mock_proc = MagicMock()
    mock_proc.communicate.return_value = ("done", "")
    mock_proc.returncode = 0
    mock_proc.poll.return_value = 0
    mock_popen.return_value = mock_proc

    GeminiRunner().run(
        RunnerInput(
            instruction="test",
            cwd=Path("."),
            timeout_seconds=10,
            model_id="gemini-3.1-pro-preview",
        )
    )

    assert mock_popen.call_args.args[0] == [
        "gemini",
        "--approval-mode",
        "yolo",
        "--skip-trust",
        "-p",
        "test",
        "--model",
        "gemini-3.1-pro-preview",
    ]
