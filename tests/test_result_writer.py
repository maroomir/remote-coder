from pathlib import Path

from app.ai.base import RunnerResult
from app.jobs.result_writer import extract_stdout_from_log, save_runner_log
from app.jobs.schemas import Job, JobRequest
from app.models import ModelName


def _job() -> Job:
    return Job(
        id="job_log_1",
        request=JobRequest(
            project="remote-coder",
            model=ModelName.CLAUDE,
            instruction="x",
            chat_id=1,
            requested_by=1,
        ),
    )


def test_extract_stdout_returns_full_stdout_excluding_stderr(tmp_path: Path):
    job = _job()
    save_runner_log(
        job,
        RunnerResult(
            exit_code=0,
            stdout="line one\n\x1b[31mcolored\x1b[0m line\n[stderr]-like body",
            stderr="boom error",
            started_at=None,
            finished_at=None,
        ),
        tmp_path,
    )

    stdout = extract_stdout_from_log(job.log_path)

    assert stdout is not None
    assert "line one" in stdout
    assert "colored line" in stdout
    assert "[stderr]-like body" in stdout
    assert "boom error" not in stdout
    assert "\x1b[" not in stdout


def test_extract_stdout_returns_none_for_missing_file(tmp_path: Path):
    assert extract_stdout_from_log(tmp_path / "missing.log") is None
