import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.ai.base import RunnerInput
from app.ai.codex import CodexRunner
from app.jobs.schemas import JobMode
from app.models import CodexSandboxMode


@patch("app.ai.base.subprocess.Popen")
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


@patch("app.ai.base.subprocess.Popen")
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


@patch("app.ai.base.subprocess.Popen")
def test_codex_runner_passes_model_id(mock_popen):
    mock_proc = MagicMock()
    mock_proc.communicate.return_value = ("", "")
    mock_proc.returncode = 0
    mock_proc.poll.return_value = 0
    mock_popen.return_value = mock_proc

    CodexRunner().run(
        RunnerInput(
            instruction="x",
            cwd=Path("."),
            timeout_seconds=10,
            model_id="gpt-5.3-codex",
        )
    )

    assert mock_popen.call_args.args[0] == [
        "codex",
        "exec",
        "--model",
        "gpt-5.3-codex",
        "--sandbox",
        "workspace-write",
        "x",
    ]


@patch("app.ai.base.subprocess.Popen")
def test_codex_runner_plan_mode_forces_read_only_sandbox(mock_popen, caplog):
    mock_proc = MagicMock()
    mock_proc.communicate.return_value = ("", "")
    mock_proc.returncode = 0
    mock_proc.poll.return_value = 0
    mock_popen.return_value = mock_proc
    with caplog.at_level(logging.INFO, logger="app.ai.codex"):
        CodexRunner(sandbox=CodexSandboxMode.WORKSPACE_WRITE).run(
            RunnerInput(
                instruction="analyze",
                cwd=Path("."),
                timeout_seconds=10,
                mode=JobMode.PLAN,
            )
        )
    command = mock_popen.call_args.args[0]
    assert command[0:4] == ["codex", "exec", "--sandbox", "read-only"]
    assert "PLAN mode" in command[4]
    assert "analyze" in command[4]


@patch("app.ai.base.subprocess.Popen")
def test_codex_runner_resumes_with_token(mock_popen):
    mock_proc = MagicMock()
    mock_proc.communicate.return_value = ("done", "")
    mock_proc.returncode = 0
    mock_proc.poll.return_value = 0
    mock_popen.return_value = mock_proc

    result = CodexRunner(sandbox=CodexSandboxMode.READ_ONLY).run(
        RunnerInput(
            instruction="follow up",
            cwd=Path("."),
            timeout_seconds=10,
            model_id="gpt-5.3-codex",
            resume_token="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        )
    )

    assert mock_popen.call_args.args[0] == [
        "codex",
        "exec",
        "--model",
        "gpt-5.3-codex",
        "--sandbox",
        "read-only",
        "resume",
        "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        "follow up",
    ]
    assert result.session_id == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def test_codex_runner_captures_new_session_id_from_rollout(tmp_path, monkeypatch):
    runner = CodexRunner()
    sessions = tmp_path / "sessions" / "2026" / "06"
    sessions.mkdir(parents=True)
    monkeypatch.setattr(runner, "_session_dir", lambda: tmp_path / "sessions")
    rollout = sessions / "rollout-2026-06-10-12345678-1234-1234-1234-1234567890ab.jsonl"
    rollout.write_text("{}", encoding="utf-8")
    captured = runner._capture_new_session_id({})
    assert captured == "12345678-1234-1234-1234-1234567890ab"


def test_codex_runner_capture_ignores_preexisting_files(tmp_path, monkeypatch):
    runner = CodexRunner()
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    old = sessions / "rollout-2026-06-09-00000000-0000-0000-0000-000000000000.jsonl"
    old.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(runner, "_session_dir", lambda: sessions)
    before = runner._snapshot_session_files()
    assert runner._capture_new_session_id(before) is None
