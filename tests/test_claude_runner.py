import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.ai.base import RunnerInput
from app.ai.claude import ClaudeRunner
from app.jobs.schemas import JobMode


@patch("app.ai.base.subprocess.Popen")
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


@patch("app.ai.base.subprocess.Popen")
def test_claude_runner_plan_wraps_prompt_with_read_only_prefix(mock_popen, caplog):
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
    assert cmd[-1] == "--dangerously-skip-permissions"


@patch("app.ai.base.subprocess.Popen")
def test_claude_runner_passes_model_id(mock_popen):
    mock_proc = MagicMock()
    mock_proc.communicate.return_value = ("done", "")
    mock_proc.returncode = 0
    mock_proc.poll.return_value = 0
    mock_popen.return_value = mock_proc

    ClaudeRunner().run(
        RunnerInput(
            instruction="test",
            cwd=Path("."),
            timeout_seconds=10,
            model_id="sonnet",
        )
    )

    assert mock_popen.call_args.args[0] == [
        "claude",
        "-p",
        "test",
        "--dangerously-skip-permissions",
        "--model",
        "sonnet",
    ]


@patch("app.ai.base.subprocess.Popen")
def test_claude_runner_sets_session_id_on_fresh_session(mock_popen):
    mock_proc = MagicMock()
    mock_proc.communicate.return_value = ("done", "")
    mock_proc.returncode = 0
    mock_proc.poll.return_value = 0
    mock_popen.return_value = mock_proc

    result = ClaudeRunner().run(
        RunnerInput(
            instruction="test",
            cwd=Path("."),
            timeout_seconds=10,
            session_id="11111111-1111-1111-1111-111111111111",
        )
    )

    assert mock_popen.call_args.args[0] == [
        "claude",
        "-p",
        "test",
        "--dangerously-skip-permissions",
        "--session-id",
        "11111111-1111-1111-1111-111111111111",
    ]
    assert result.session_id == "11111111-1111-1111-1111-111111111111"


@patch("app.ai.base.subprocess.Popen")
def test_claude_runner_resumes_with_token(mock_popen):
    mock_proc = MagicMock()
    mock_proc.communicate.return_value = ("done", "")
    mock_proc.returncode = 0
    mock_proc.poll.return_value = 0
    mock_popen.return_value = mock_proc

    result = ClaudeRunner().run(
        RunnerInput(
            instruction="test",
            cwd=Path("."),
            timeout_seconds=10,
            session_id="11111111-1111-1111-1111-111111111111",
            resume_token="11111111-1111-1111-1111-111111111111",
        )
    )

    cmd = mock_popen.call_args.args[0]
    assert "--resume" in cmd and "--session-id" not in cmd
    assert cmd[cmd.index("--resume") + 1] == "11111111-1111-1111-1111-111111111111"
    assert result.session_id == "11111111-1111-1111-1111-111111111111"
