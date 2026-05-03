"""app/monitoring 코드 카운터 및 포맷 단위 테스트."""

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
    assert "최근 Job 사용량" in text
    assert "관측된 세부 모델: ChatGPT 5.5" in text
    assert "input=1,200" in text
    assert "output=300" in text
