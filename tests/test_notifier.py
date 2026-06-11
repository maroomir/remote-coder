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
    assert "text" not in payload


@respx.mock
def test_notifier_answer_callback_query_with_toast_text():
    route = respx.post("https://api.telegram.org/bottoken/answerCallbackQuery").mock(
        return_value=Response(200, json={"ok": True})
    )
    store = type("Store", (), {"get": lambda self: AdvancedSettings(ui_language=UiLanguage.KOREAN)})()
    notifier = TelegramNotifier("token", store)
    notifier.answer_callback_query("cq_x", text="작업 중단 요청 완료", show_alert=True)
    payload = json.loads(route.calls[0].request.content)
    assert payload["text"]
    assert payload["show_alert"] is True


@respx.mock
def test_notifier_edit_message_sends_entities_and_keyboard():
    from app.telegram.commands import InlineButton

    route = respx.post("https://api.telegram.org/bottoken/editMessageText").mock(
        return_value=Response(200, json={"ok": True, "result": {"message_id": 7}})
    )
    notifier = TelegramNotifier("token")
    buttons = [[InlineButton("claude", "/model claude")]]
    ok = notifier.edit_message(42, 7, "Model settings\n\n- Current default model: claude", buttons)
    assert ok is True
    payload = json.loads(route.calls[0].request.content)
    assert payload["chat_id"] == 42
    assert payload["message_id"] == 7
    assert payload["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "/model claude"
    assert payload["entities"][0]["type"] == "bold"


@respx.mock
def test_notifier_edit_message_not_modified_is_success_without_retry():
    route = respx.post("https://api.telegram.org/bottoken/editMessageText").mock(
        return_value=Response(400, json={"ok": False, "description": "Bad Request: message is not modified"})
    )
    notifier = TelegramNotifier("token")
    ok = notifier.edit_message(1, 2, "same", [])
    assert ok is True
    assert route.call_count == 1


@respx.mock
def test_notifier_edit_message_not_found_returns_false():
    route = respx.post("https://api.telegram.org/bottoken/editMessageText").mock(
        return_value=Response(400, json={"ok": False, "description": "Bad Request: message to edit not found"})
    )
    notifier = TelegramNotifier("token")
    ok = notifier.edit_message(1, 2, "x", [])
    assert ok is False
    assert route.call_count == 1


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


def _job_with_session(session_id, *, mode=JobMode.AGENT, status=JobStatus.SUCCEEDED, **extra):
    from app.telegram.notifier import build_job_result_message  # noqa: F401

    return Job(
        id="j-sess",
        request=JobRequest(
            project="proj",
            model=ModelName.CLAUDE,
            instruction="x",
            chat_id=1,
            requested_by=1,
            mode=mode,
            session_id=session_id,
        ),
        status=status,
        **extra,
    )


def test_build_job_result_includes_session_id_when_set():
    from app.telegram.notifier import build_job_result_message

    sid = "11111111-1111-1111-1111-111111111111"
    agent = _job_with_session(sid, branch="b", commit_hash="abc", changed_files=["a.py"])
    assert f"- Session ID: {sid}" in build_job_result_message(agent)

    readonly = _job_with_session(sid, mode=JobMode.ASK)
    text = build_job_result_message(readonly)
    assert "[ask] Completed" in text
    assert f"- Session ID: {sid}" in text

    failed = _job_with_session(sid, status=JobStatus.FAILED, error="boom")
    assert f"- Session ID: {sid}" in build_job_result_message(failed)

    cancelled = _job_with_session(sid, status=JobStatus.CANCELLED)
    assert f"- Session ID: {sid}" in build_job_result_message(cancelled)


def test_build_job_result_omits_session_id_when_absent():
    from app.telegram.notifier import build_job_result_message

    job = _job_with_session(None, branch="b", commit_hash="abc", changed_files=["a.py"])
    assert "Session ID" not in build_job_result_message(job)


def test_build_job_accepted_includes_session_id():
    from app.telegram.notifier import build_job_accepted_message

    sid = "22222222-2222-2222-2222-222222222222"
    text, _ = build_job_accepted_message(_job_with_session(sid, status=JobStatus.QUEUED))
    assert f"- Session ID: {sid}" in text


@respx.mock
def test_notifier_keeps_session_id_under_korean_ui():
    route = respx.post("https://api.telegram.org/bottoken/sendMessage").mock(
        return_value=Response(200, json={"ok": True})
    )
    store = type("Store", (), {"get": lambda self: AdvancedSettings(ui_language=UiLanguage.KOREAN)})()
    notifier = TelegramNotifier("token", store)
    sid = "33333333-3333-3333-3333-333333333333"
    notifier.send_job_result(
        _job_with_session(sid, branch="b", commit_hash="abc", changed_files=["a.py"])
    )
    payload = json.loads(route.calls[0].request.content.decode())
    assert "작업 완료" in payload["text"]
    assert f"- Session ID: {sid}" in payload["text"]


def _job(mode=JobMode.PLAN, status=JobStatus.SUCCEEDED, summary="plan body", **kw):
    return Job(
        id="j-btn",
        request=JobRequest(
            project="proj", model=ModelName.CLAUDE, instruction="x", chat_id=1, requested_by=1, mode=mode
        ),
        status=status,
        runner_stdout_summary=summary,
        **kw,
    )


def test_build_job_result_buttons_for_plan_success():
    from app.telegram.notifier import build_job_result_buttons

    rows = build_job_result_buttons(_job(mode=JobMode.PLAN, status=JobStatus.SUCCEEDED))
    assert len(rows) == 1 and len(rows[0]) == 1
    assert rows[0][0].callback_data == "__plan_exec__:j-btn"


def test_build_job_result_buttons_empty_for_non_plan_or_failure():
    from app.telegram.notifier import build_job_result_buttons

    assert build_job_result_buttons(_job(mode=JobMode.ASK, status=JobStatus.SUCCEEDED)) == []
    assert build_job_result_buttons(_job(mode=JobMode.AGENT, status=JobStatus.SUCCEEDED)) == []
    assert build_job_result_buttons(_job(mode=JobMode.PLAN, status=JobStatus.FAILED)) == []


def test_build_job_result_buttons_for_committed_agent_and_fix_success():
    from app.telegram.notifier import build_job_result_buttons

    for mode in (JobMode.AGENT, JobMode.AGENT_FIX):
        rows = build_job_result_buttons(
            _job(
                mode=mode,
                status=JobStatus.SUCCEEDED,
                branch="remote-fix",
                commit_hash="abc1234",
            )
        )
        assert rows[0][0].label == "Open PR"
        assert rows[0][0].callback_data == "/pr remote-fix"


def test_build_job_result_buttons_requires_agent_commit_and_branch():
    from app.telegram.notifier import build_job_result_buttons

    assert build_job_result_buttons(
        _job(mode=JobMode.AGENT, status=JobStatus.SUCCEEDED, branch="remote-no-commit")
    ) == []
    assert build_job_result_buttons(
        _job(mode=JobMode.AGENT, status=JobStatus.SUCCEEDED, commit_hash="abc1234")
    ) == []


@respx.mock
def test_notifier_plan_result_attaches_run_plan_button():
    route = respx.post("https://api.telegram.org/bottoken/sendMessage").mock(
        return_value=Response(200, json={"ok": True, "result": {"message_id": 5}})
    )
    notifier = TelegramNotifier("token")
    notifier.send_job_result(_job(mode=JobMode.PLAN, status=JobStatus.SUCCEEDED))
    payload = json.loads(route.calls[-1].request.content)
    kb = payload["reply_markup"]["inline_keyboard"]
    assert kb[0][0]["text"] == "Run plan"
    assert kb[0][0]["callback_data"] == "__plan_exec__:j-btn"


@respx.mock
def test_notifier_long_plan_result_button_only_on_last_chunk():
    route = respx.post("https://api.telegram.org/bottoken/sendMessage").mock(
        return_value=Response(200, json={"ok": True, "result": {"message_id": 5}})
    )
    notifier = TelegramNotifier("token")
    notifier.send_job_result(_job(mode=JobMode.PLAN, status=JobStatus.SUCCEEDED, summary="B" * 5000))
    assert len(route.calls) >= 2
    for call in route.calls[:-1]:
        assert "reply_markup" not in json.loads(call.request.content)
    assert "reply_markup" in json.loads(route.calls[-1].request.content)


@respx.mock
def test_notifier_long_agent_result_pr_button_only_on_last_chunk():
    route = respx.post("https://api.telegram.org/bottoken/sendMessage").mock(
        return_value=Response(200, json={"ok": True, "result": {"message_id": 5}})
    )
    notifier = TelegramNotifier("token")
    notifier.send_job_result(
        _job(
            mode=JobMode.AGENT,
            status=JobStatus.SUCCEEDED,
            summary="B" * 5000,
            branch="remote-fix",
            commit_hash="abc1234",
        )
    )
    assert len(route.calls) >= 2
    for call in route.calls[:-1]:
        assert "reply_markup" not in json.loads(call.request.content)
    keyboard = json.loads(route.calls[-1].request.content)["reply_markup"]["inline_keyboard"]
    assert keyboard[0][0]["callback_data"] == "/pr remote-fix"


def test_build_job_heartbeat_message_includes_elapsed_and_accepted():
    from app.telegram.notifier import build_job_heartbeat_message

    text = build_job_heartbeat_message(_job(mode=JobMode.AGENT, status=JobStatus.QUEUED), 3)
    assert "Job accepted" in text
    assert "Running (3m elapsed)" in text


def test_build_job_heartbeat_message_korean():
    from app.telegram.i18n import translate_text
    from app.telegram.notifier import build_job_heartbeat_message

    text = build_job_heartbeat_message(_job(mode=JobMode.AGENT, status=JobStatus.QUEUED), 2)
    assert "실행 중 (2분 경과)" in translate_text(text, UiLanguage.KOREAN)
