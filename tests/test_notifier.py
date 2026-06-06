import json
import logging

import respx
from httpx import Response
from pathlib import Path

from app.admin.advanced_settings import AdvancedSettings
from app.jobs.schemas import Job, JobMode, JobRequest, JobStatus
from app.models import ModelName, UiLanguage
from app.telegram.notifier import TelegramNotifier


@respx.mock
def test_notifier_send_job_accepted_includes_mode_for_plan_ask():
    route = respx.post("https://api.telegram.org/bottoken/sendMessage").mock(
        return_value=Response(200, json={"ok": True})
    )
    store = type("Store", (), {"get": lambda self: AdvancedSettings(ui_language=UiLanguage.KOREAN)})()
    notifier = TelegramNotifier("token", store)
    for mode, expected in ((JobMode.PLAN, "모드: plan"), (JobMode.ASK, "모드: ask")):
        route.calls.clear()
        job = Job(
            id="j-mode",
            request=JobRequest(
                project="proj",
                model=ModelName.CLAUDE,
                instruction="x",
                chat_id=1,
                requested_by=1,
                mode=mode,
            ),
        )
        notifier.send_job_accepted(job)
        payload = json.loads(route.calls[0].request.content.decode())
        assert expected in payload["text"]
        assert "모델: claude" in payload["text"]


@respx.mock
def test_notifier_send_job_accepted_includes_detail_model():
    route = respx.post("https://api.telegram.org/bottoken/sendMessage").mock(
        return_value=Response(200, json={"ok": True})
    )
    store = type("Store", (), {"get": lambda self: AdvancedSettings(ui_language=UiLanguage.KOREAN)})()
    notifier = TelegramNotifier("token", store)
    job = Job(
        id="j-detail",
        request=JobRequest(
            project="proj",
            model=ModelName.CODEX,
            model_id="gpt-5.3-codex",
            instruction="x",
            chat_id=1,
            requested_by=1,
        ),
    )

    notifier.send_job_accepted(job)

    payload = json.loads(route.calls[0].request.content.decode())
    assert "모델: codex / gpt-5.3-codex" in payload["text"]


@respx.mock
def test_notifier_uses_english_when_advanced_language_default():
    route = respx.post("https://api.telegram.org/bottoken/sendMessage").mock(
        return_value=Response(200, json={"ok": True})
    )
    advanced_settings_store = type("Store", (), {"get": lambda self: AdvancedSettings()})()
    notifier = TelegramNotifier("token", advanced_settings_store)
    job = Job(
        id="j-en",
        request=JobRequest(
            project="proj",
            model=ModelName.CLAUDE,
            instruction="x",
            chat_id=1,
            requested_by=1,
        ),
    )

    notifier.send_job_accepted(job)

    payload = json.loads(route.calls[0].request.content.decode())
    assert "Job accepted" in payload["text"]
    assert "Project: proj" in payload["text"]
    assert payload["reply_markup"]["inline_keyboard"][0][0]["text"] == "Stop job"


@respx.mock
def test_notifier_send_job_result_plan_succeeded_compact_format():
    route = respx.post("https://api.telegram.org/bottoken/sendMessage").mock(
        return_value=Response(200, json={"ok": True})
    )
    notifier = TelegramNotifier("token")
    job = Job(
        id="j-plan",
        request=JobRequest(
            project="proj",
            model=ModelName.CLAUDE,
            instruction="x",
            chat_id=1,
            requested_by=1,
            mode=JobMode.PLAN,
        ),
        status=JobStatus.SUCCEEDED,
        branch="ignored-branch",
        commit_hash="dead",
        changed_files=["should_not_show.py"],
        runner_stdout_summary="step one then two",
        runner_actual_model="claude-3",
        runner_token_usage={"input": 10, "output": 5},
    )
    notifier.send_job_result(job)
    payload = route.calls[0].request.content.decode()
    assert "[plan] Completed" in payload
    assert "step one then two" in payload
    assert "Branch:" not in payload
    assert "Commit:" not in payload
    assert "Changed files:" not in payload
    assert "Model used: claude-3" in payload
    assert "Token usage: 15" in payload


@respx.mock
def test_notifier_send_job_result_ask_succeeded_compact_format():
    route = respx.post("https://api.telegram.org/bottoken/sendMessage").mock(
        return_value=Response(200, json={"ok": True})
    )
    notifier = TelegramNotifier("token")
    job = Job(
        id="j-ask",
        request=JobRequest(
            project="proj",
            model=ModelName.CODEX,
            instruction="q",
            chat_id=2,
            requested_by=1,
            mode=JobMode.ASK,
        ),
        status=JobStatus.SUCCEEDED,
        runner_stdout_summary="answer text",
    )
    notifier.send_job_result(job)
    payload = route.calls[0].request.content.decode()
    assert "[ask] Completed" in payload
    assert "answer text" in payload
    assert "Branch:" not in payload


@respx.mock
def test_notifier_send_job_result_plan_failure_prefix_only():
    route = respx.post("https://api.telegram.org/bottoken/sendMessage").mock(
        return_value=Response(200, json={"ok": True})
    )
    notifier = TelegramNotifier("token")
    job = Job(
        id="j-fail",
        request=JobRequest(
            project="proj",
            model=ModelName.GEMINI,
            instruction="x",
            chat_id=1,
            requested_by=1,
            mode=JobMode.PLAN,
        ),
        status=JobStatus.FAILED,
        error="boom",
        error_stage="runner",
    )
    notifier.send_job_result(job)
    payload = route.calls[0].request.content.decode()
    assert "[plan] ❌ Job failed" in payload
    assert "boom" in payload


@respx.mock
def test_notifier_send_job_result_plan_cancelled_has_mode_prefix():
    route = respx.post("https://api.telegram.org/bottoken/sendMessage").mock(
        return_value=Response(200, json={"ok": True})
    )
    notifier = TelegramNotifier("token")
    job = Job(
        id="j-can",
        request=JobRequest(
            project="proj",
            model=ModelName.CLAUDE,
            instruction="x",
            chat_id=1,
            requested_by=1,
            mode=JobMode.PLAN,
        ),
        status=JobStatus.CANCELLED,
    )
    notifier.send_job_result(job)
    payload = route.calls[0].request.content.decode()
    assert "[plan] ⛔ Job cancelled" in payload


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
    assert "AI response" in payload
    assert "done summary" in payload
    assert "Model used" in payload
    assert "Token usage" in payload


@respx.mock
def test_notifier_send_job_result_success_includes_runner_usage():
    route = respx.post("https://api.telegram.org/bottoken/sendMessage").mock(
        return_value=Response(200, json={"ok": True})
    )
    notifier = TelegramNotifier("token")
    job = Job(
        id="j-usage",
        request=JobRequest(
            project="proj", model=ModelName.CODEX, instruction="x", chat_id=1, requested_by=1
        ),
        status=JobStatus.SUCCEEDED,
        branch="b",
        commit_hash="abc",
        changed_files=["a.py"],
        runner_actual_model="ChatGPT 5.5",
        runner_token_usage={"input": 1200, "output": 300},
    )
    notifier.send_job_result(job)
    payload = route.calls[0].request.content.decode()
    assert "Model used: ChatGPT 5.5" in payload
    assert "Token usage: 1,500" in payload


@respx.mock
def test_notifier_send_job_result_uses_requested_detail_model_when_actual_missing():
    route = respx.post("https://api.telegram.org/bottoken/sendMessage").mock(
        return_value=Response(200, json={"ok": True})
    )
    notifier = TelegramNotifier("token")
    job = Job(
        id="j-detail-result",
        request=JobRequest(
            project="proj",
            model=ModelName.CODEX,
            model_id="gpt-5.3-codex",
            instruction="x",
            chat_id=1,
            requested_by=1,
        ),
        status=JobStatus.SUCCEEDED,
        branch="b",
        commit_hash="abc",
        changed_files=["a.py"],
    )

    notifier.send_job_result(job)

    payload = route.calls[0].request.content.decode()
    assert "Model used: codex / gpt-5.3-codex" in payload


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
    assert "not created" in payload or "none" in payload


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
    assert "Failure stage" in payload
    assert "Log path" in payload
    assert "Failure output summary" in payload
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
    marker = "\n\nAI response:\n"
    assert combined.find(marker) != -1
    assert combined.endswith(long_ai)
    assert "Job completed" in combined
    assert "truncated" not in combined


@respx.mock
def test_notifier_send_text_skip_body_preserves_source_under_english_ui():
    route = respx.post("https://api.telegram.org/bottoken/sendMessage").mock(
        return_value=Response(200, json={"ok": True, "result": {"message_id": 9}})
    )
    store = type("Store", (), {"get": lambda self: AdvancedSettings(ui_language=UiLanguage.ENGLISH)})()
    notifier = TelegramNotifier("token", store)
    raw = "일반 자연어 작업 요청입니다."
    notifier.send_text(3, raw, skip_body_i18n=True)
    payload = json.loads(route.calls[0].request.content)
    assert payload["text"] == raw


@respx.mock
def test_notifier_send_text_logs_outbound_success(caplog):
    route = respx.post("https://api.telegram.org/bottoken/sendMessage").mock(
        return_value=Response(200, json={"ok": True, "result": {"message_id": 456}})
    )
    with caplog.at_level(logging.INFO, logger="app.telegram.outbound"):
        notifier = TelegramNotifier("token")
        message_id = notifier.send_text(42, "hi")
    assert route.called
    assert message_id == 456
    assert any(r.name == "app.telegram.outbound" and "sent text" in r.getMessage() for r in caplog.records)
    assert any(getattr(r, "chat_id", None) == 42 for r in caplog.records)


@respx.mock
def test_notifier_send_text_logs_outbound_warning_on_failure(caplog):
    route = respx.post("https://api.telegram.org/bottoken/sendMessage").mock(
        return_value=Response(500, json={"ok": False})
    )
    with caplog.at_level(logging.WARNING, logger="app.telegram.outbound"):
        notifier = TelegramNotifier("token")
        notifier.send_text(7, "x")
    assert route.call_count >= 1
    assert any("sendMessage failed" in r.getMessage() for r in caplog.records)


@respx.mock
def test_notifier_send_with_buttons_sends_inline_keyboard():
    from app.telegram.commands import InlineButton

    route = respx.post("https://api.telegram.org/bottoken/sendMessage").mock(
        return_value=Response(200, json={"ok": True, "result": {"message_id": 789}})
    )
    notifier = TelegramNotifier("token")
    buttons = [[InlineButton("claude", "/model claude"), InlineButton("codex", "/model codex")]]
    message_id = notifier.send_with_buttons(42, "Help", buttons)
    assert route.called
    assert message_id == 789
    payload = json.loads(route.calls[0].request.content)
    assert payload["chat_id"] == 42
    assert payload["text"] == "Help"
    assert "reply_markup" in payload
    kb = payload["reply_markup"]["inline_keyboard"]
    assert kb[0][0]["text"] == "claude"
    assert kb[0][0]["callback_data"] == "/model claude"
    assert kb[0][1]["text"] == "codex"


@respx.mock
def test_notifier_answer_callback_query():
    route = respx.post("https://api.telegram.org/bottoken/answerCallbackQuery").mock(
        return_value=Response(200, json={"ok": True})
    )
    notifier = TelegramNotifier("token")
    notifier.answer_callback_query("cq_abc")
    assert route.called
    payload = json.loads(route.calls[0].request.content)
    assert payload["callback_query_id"] == "cq_abc"


@respx.mock
def test_notifier_keeps_korean_when_ui_language_is_korean():
    route = respx.post("https://api.telegram.org/bottoken/sendMessage").mock(
        return_value=Response(200, json={"ok": True})
    )
    store = type("Store", (), {"get": lambda self: AdvancedSettings(ui_language=UiLanguage.KOREAN)})()
    notifier = TelegramNotifier("token", store)
    job = Job(
        id="jk",
        request=JobRequest(
            project="p",
            model=ModelName.CLAUDE,
            instruction="x",
            chat_id=1,
            requested_by=1,
        ),
        status=JobStatus.SUCCEEDED,
        branch="main",
        commit_hash="abc",
        changed_files=[],
    )
    notifier.send_job_result(job)
    payload = route.calls[0].request.content.decode()
    assert "작업 완료" in payload
    assert "프로젝트" in payload


@respx.mock
def test_notifier_does_not_translate_ai_response_body_under_korean_ui():
    route = respx.post("https://api.telegram.org/bottoken/sendMessage").mock(
        return_value=Response(200, json={"ok": True})
    )
    store = type("Store", (), {"get": lambda self: AdvancedSettings(ui_language=UiLanguage.KOREAN)})()
    notifier = TelegramNotifier("token", store)
    job = Job(
        id="j-ai",
        request=JobRequest(
            project="proj",
            model=ModelName.CLAUDE,
            instruction="x",
            chat_id=1,
            requested_by=1,
        ),
        status=JobStatus.SUCCEEDED,
        runner_stdout_summary="Project: keep this exact\nModel: keep this exact",
    )

    notifier.send_job_result(job)

    payload = json.loads(route.calls[0].request.content)
    assert "AI 응답:" in payload["text"]
    assert "Project: keep this exact" in payload["text"]
    assert "Model: keep this exact" in payload["text"]
    assert "프로젝트: keep this exact" not in payload["text"]
