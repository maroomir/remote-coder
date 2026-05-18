import json
from datetime import datetime
from pathlib import Path

from app.jobs.schemas import Job, JobRequest, JobStatus
from app.monitoring.code import ProjectCodeStats, count_project_code
from app.monitoring.memory import format_memory_monitor
from app.monitoring.model import format_model_monitor
from app.models import ModelName
from app.telegram.conversation import ConversationDbChatStats


def test_count_project_code_skips_git_and_counts_py(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    (root / ".git").mkdir()
    (root / ".git" / "config").write_bytes(b"[core]\n")
    (root / "main.py").write_text("a\nb\nc\n", encoding="utf-8")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "x.js").write_text("noop\n", encoding="utf-8")

    stats = count_project_code(root, max_files=100)
    assert isinstance(stats, ProjectCodeStats)
    assert stats.files_scanned == 1
    assert stats.total_lines == 4


def test_format_memory_monitor_line():
    stats = ConversationDbChatStats(
        db_path=Path("/tmp/x.sqlite3"),
        db_exists=True,
        db_size_bytes=1024,
        total_rows=3,
        rows_by_role={"user": 2, "job_result": 1},
    )
    text = format_memory_monitor(stats, "proj-a", 99)
    assert "proj-a" in text and "99" in text
    assert "1024" in text


def test_format_model_monitor_codex_not_installed():
    text = format_model_monitor(ModelName.CODEX, timeout_seconds=2)
    assert "[Codex]" in text


def test_format_model_monitor_gemini_not_installed():
    text = format_model_monitor(ModelName.GEMINI, timeout_seconds=2)
    assert "[Gemini]" in text


def test_format_model_monitor_includes_recent_job_usage():
    job = Job(
        id="job-usage",
        request=JobRequest(
            project="remote-coder",
            model=ModelName.CODEX,
            instruction="x",
            chat_id=7,
            requested_by=1,
        ),
        status=JobStatus.SUCCEEDED,
        runner_stdout_summary="model: ChatGPT 5.5\ninput tokens: 1,200\noutput tokens: 300",
    )
    text = format_model_monitor(
        ModelName.CODEX,
        timeout_seconds=2,
        recent_jobs=[job],
        chat_id=7,
        project="remote-coder",
    )
    assert "Recent job usage" in text
    assert "Observed detailed model: ChatGPT 5.5" in text
    assert "input=1,200" in text
    assert "output=300" in text


def test_format_model_monitor_prefers_structured_usage():
    job = Job(
        id="job-structured-usage",
        request=JobRequest(
            project="remote-coder",
            model=ModelName.CODEX,
            instruction="x",
            chat_id=7,
            requested_by=1,
        ),
        status=JobStatus.SUCCEEDED,
        runner_stdout_summary="model: older\ninput tokens: 1",
        runner_actual_model="ChatGPT 5.5",
        runner_token_usage={"input": 1200, "output": 300},
    )
    text = format_model_monitor(
        ModelName.CODEX,
        timeout_seconds=2,
        recent_jobs=[job],
        chat_id=7,
        project="remote-coder",
    )
    assert "Observed detailed model: ChatGPT 5.5" in text
    assert "Observed tokens: 1,500" in text


def test_format_model_monitor_includes_codex_local_rate_limits(tmp_path: Path, monkeypatch):
    codex_home = tmp_path / ".codex"
    session_dir = codex_home / "sessions" / "2026" / "05" / "07"
    session_dir.mkdir(parents=True)
    session = session_dir / "rollout.jsonl"
    session.write_text(
        json.dumps(
            {
                "timestamp": "2026-05-07T01:00:00Z",
                "type": "event_msg",
                "payload": {
                    "info": {
                        "total_token_usage": {
                            "input_tokens": 100,
                            "output_tokens": 25,
                            "total_tokens": 125,
                        }
                    },
                    "rate_limits": {
                        "plan_type": "plus",
                        "primary": {
                            "used_percent": 56.0,
                            "window_minutes": 300,
                            "resets_at": 1778119200,
                        },
                        "secondary": {
                            "used_percent": 10.0,
                            "window_minutes": 10080,
                            "resets_at": 1778724000,
                        },
                    },
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    text = format_model_monitor(ModelName.CODEX, timeout_seconds=2)

    assert "Local usage/quota snapshot" in text
    assert "Plan/account type: plus" in text
    assert "5-hour limit: remaining 44%" in text
    assert "Weekly limit: remaining 90%" in text
    assert "Observed tokens: 125" in text


def test_format_model_monitor_includes_claude_local_transcript_usage(tmp_path: Path, monkeypatch):
    claude_home = tmp_path / ".claude"
    project_dir = claude_home / "projects" / "example"
    project_dir.mkdir(parents=True)
    transcript = project_dir / "session.jsonl"
    transcript.write_text(
        json.dumps(
            {
                "timestamp": "2026-05-07T02:00:00Z",
                "type": "assistant",
                "message": {
                    "model": "claude-sonnet-4-6",
                    "usage": {
                        "input_tokens": 10,
                        "cache_read_input_tokens": 20,
                        "output_tokens": 5,
                    },
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude_home))

    text = format_model_monitor(ModelName.CLAUDE, timeout_seconds=2)

    assert "Local usage/quota snapshot" in text
    assert "Observed detailed model: claude-sonnet-4-6" in text
    assert "input=10" in text
    assert "output=5" in text
    assert "not account remaining quota snapshots" in text


def test_format_model_monitor_includes_gemini_local_chat_usage(tmp_path: Path, monkeypatch):
    gemini_home = tmp_path / ".gemini"
    chat_dir = gemini_home / "tmp" / "proj" / "chats"
    chat_dir.mkdir(parents=True)
    chat = chat_dir / "session.jsonl"
    today = datetime.now().astimezone().replace(microsecond=0)
    chat.write_text(
        json.dumps(
            {
                "timestamp": today.isoformat(),
                "type": "gemini",
                "tokens": {"input": 30, "output": 7, "total": 37},
                "model": "gemini-3-flash-preview",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("GEMINI_HOME", str(gemini_home))

    text = format_model_monitor(ModelName.GEMINI, timeout_seconds=2)

    assert "Local usage/quota snapshot" in text
    assert "Observed detailed model: gemini-3-flash-preview" in text
    assert "Requests today from local logs: 1" in text
    assert "input=30" in text
    assert "not account remaining quota snapshots" in text
