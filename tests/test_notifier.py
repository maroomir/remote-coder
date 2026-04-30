import json

import respx
from httpx import Response
from pathlib import Path

from app.jobs.schemas import Job, JobRequest, JobStatus
from app.models import ModelName
from app.telegram.notifier import TelegramNotifier


@respx.mock
def test_notifier_send_job_result_success():
    route = respx.post("https://api.telegram.org/bottoken/sendMessage").mock(
        return_value=Response(200, json={"ok": True})
    )
    notifier = TelegramNotifier("token")
    job = Job(
        id="j1",
        request=JobRequest(
            project="proj", model=ModelName.CLAUDE, instruction="x", chat_id=1, requested_by=1
        ),
        status=JobStatus.SUCCEEDED,
        branch="b",
        commit_hash="abc",
        changed_files=["a.py"],
        runner_stdout_summary="done summary",
    )
    notifier.send_job_result(job)
    assert route.called
    payload = route.calls[0].request.content.decode()
    assert "AI 응답" in payload
    assert "done summary" in payload


@respx.mock
def test_notifier_success_without_branch_shows_no_branch_message():
    route = respx.post("https://api.telegram.org/bottoken/sendMessage").mock(
        return_value=Response(200, json={"ok": True})
    )
    notifier = TelegramNotifier("token")
    job = Job(
        id="j0",
        request=JobRequest(
            project="proj", model=ModelName.CLAUDE, instruction="x", chat_id=1, requested_by=1
        ),
        status=JobStatus.SUCCEEDED,
        branch=None,
        commit_hash=None,
        changed_files=[],
    )
    notifier.send_job_result(job)
    payload = route.calls[0].request.content.decode()
    assert "미생성" in payload or "없음" in payload


@respx.mock
def test_notifier_send_job_result_failure_includes_log_path():
    route = respx.post("https://api.telegram.org/bottoken/sendMessage").mock(
        return_value=Response(200, json={"ok": True})
    )
    notifier = TelegramNotifier("token")
    job = Job(
        id="j2",
        request=JobRequest(
            project="proj", model=ModelName.CLAUDE, instruction="x", chat_id=1, requested_by=1
        ),
        status=JobStatus.FAILED,
        error="runner failed",
        error_stage="runner",
        log_path=Path("/tmp/job.log"),
        runner_stderr_summary="permission denied",
    )
    notifier.send_job_result(job)
    assert route.called
    payload = route.calls[0].request.content.decode()
    assert "실패 단계" in payload
    assert "로그 경로" in payload
    assert "실패 출력 요약" in payload
    assert "permission denied" in payload


@respx.mock
def test_notifier_splits_long_job_result_message():
    route = respx.post("https://api.telegram.org/bottoken/sendMessage").mock(
        return_value=Response(200, json={"ok": True})
    )
    notifier = TelegramNotifier("token")
    long_ai = "A" * 5000
    job = Job(
        id="j3",
        request=JobRequest(
            project="proj", model=ModelName.CODEX, instruction="x", chat_id=1, requested_by=1
        ),
        status=JobStatus.SUCCEEDED,
        branch="b",
        commit_hash="-",
        changed_files=[],
        runner_stdout_summary=long_ai,
    )
    notifier.send_job_result(job)
    assert len(route.calls) >= 2
    combined = ""
    for call in route.calls:
        payload = json.loads(call.request.content.decode())
        assert len(payload["text"]) <= 4096
        combined += payload["text"]
    marker = "\n\nAI 응답:\n"
    assert combined.find(marker) != -1
    assert combined.endswith(long_ai)
    assert "작업 완료" in combined
    assert "truncated" not in combined
