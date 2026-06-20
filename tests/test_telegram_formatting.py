import json

import respx
from httpx import Response

from app.jobs.schemas import Job, JobRequest, JobStatus
from app.models import ModelName
from app.telegram.formatting import build_message_entities, prepare_outgoing
from app.telegram.notifier import TelegramNotifier


def test_entities_bold_first_line_of_multiline_message():
    text = "✅ Job accepted\n\n- Job ID: j1\n- Project: proj"
    entities = build_message_entities(text)
    assert entities[0] == {"type": "bold", "offset": 0, "length": len("✅ Job accepted")}


def test_entities_skip_single_line_message():
    assert build_message_entities("Cancelled the work request.") == []


def test_entities_code_for_job_id_branch_commit_values():
    text = (
        "✅ Job completed\n\n"
        "- Job ID: job_abc\n"
        "- Project: proj\n"
        "- Branch: remote-fix\n"
        "- Commit: deadbeef\n"
    )
    entities = build_message_entities(text)
    code_entities = [e for e in entities if e["type"] == "code"]
    job_id_offset = text.index("job_abc")
    branch_offset = text.index("remote-fix")
    commit_offset = text.index("deadbeef")
    assert {"type": "code", "offset": job_id_offset, "length": len("job_abc")} in code_entities
    assert {"type": "code", "offset": branch_offset, "length": len("remote-fix")} in code_entities
    assert {"type": "code", "offset": commit_offset, "length": len("deadbeef")} in code_entities


def test_entities_code_for_session_id_value():
    text = (
        "✅ Job completed\n\n"
        "- Job ID: job_abc\n"
        "- Session ID: 11111111-1111-1111-1111-111111111111\n"
        "- Project: proj\n"
    )
    entities = build_message_entities(text)
    code_entities = [e for e in entities if e["type"] == "code"]
    sid = "11111111-1111-1111-1111-111111111111"
    sid_offset = text.index(sid)
    assert {"type": "code", "offset": sid_offset, "length": len(sid)} in code_entities


def test_entities_skip_placeholder_values_in_parentheses():
    text = "✅ Job completed\n\n- Branch: (none - no branch; no changes)\n- Commit: -"
    entities = build_message_entities(text)
    assert all(e["type"] != "code" or e["length"] != 0 for e in entities)
    assert not [e for e in entities if e["type"] == "code" and e["offset"] == text.index("(none")]


def test_entities_use_utf16_offsets_for_astral_emoji():
    text = "🚀 Done\n- Job ID: j1"
    entities = build_message_entities(text)
    bold = entities[0]
    assert bold["offset"] == 0
    assert bold["length"] == len("🚀 Done") + 1  # 🚀 counts as 2 UTF-16 units
    code = [e for e in entities if e["type"] == "code"][0]
    assert code["offset"] == text.index("j1") + 1
    assert code["length"] == len("j1")


def test_entities_stop_after_ai_response_marker():
    text = (
        "✅ Job completed\n\n"
        "- Job ID: j1\n\n"
        "AI response:\n"
        "Options\n"
        "- Branch: looks-like-a-label\n"
    )
    entities = build_message_entities(text)
    marker_offset = text.index("AI response:")
    assert {"type": "bold", "offset": marker_offset, "length": len("AI response:")} in entities
    assert all(e["offset"] <= marker_offset for e in entities)


def test_prepare_outgoing_keeps_list_text_without_pre_entity():
    text = "Header\n\n- Project: remote\n- Model: claude"
    out_text, entities = prepare_outgoing(text)
    assert all(e["type"] != "pre" for e in entities)
    assert out_text == text


def test_entities_mark_help_command_signature_as_code():
    text = "Help\n\nCommands:\n- /model <claude|codex|gemini|ollama>\n  Change the default model"

    entities = build_message_entities(text)

    signature = "/model <claude|codex|gemini|ollama>"
    assert {
        "type": "code",
        "offset": text.index(signature),
        "length": len(signature),
    } in entities


def test_command_entity_offset_uses_utf16_units_after_emoji():
    text = "🚀 Help\n\nCommands:\n- /model"

    entities = build_message_entities(text)

    command = next(e for e in entities if e["type"] == "code")
    expected_offset = len(text[: text.index("/model")].encode("utf-16-le")) // 2
    assert command["offset"] == expected_offset


def test_entities_bold_known_section_headings():
    text = "Help\n\nOptions\n- model:\n\nCommands:\n- /model"
    entities = build_message_entities(text)
    assert {"type": "bold", "offset": 0, "length": len("Help")} in entities
    assert {"type": "bold", "offset": text.index("Options"), "length": len("Options")} in entities
    assert {"type": "bold", "offset": text.index("Commands:"), "length": len("Commands:")} in entities


@respx.mock
def test_notifier_send_text_includes_entities_and_keeps_text_plain():
    route = respx.post("https://api.telegram.org/bottoken/sendMessage").mock(
        return_value=Response(200, json={"ok": True})
    )
    notifier = TelegramNotifier("token")
    text = "✅ Job accepted\n\n- Job ID: j1"
    notifier.send_text(1, text)
    payload = json.loads(route.calls[0].request.content)
    assert payload["text"] == text
    assert payload["entities"][0]["type"] == "bold"


@respx.mock
def test_notifier_send_with_buttons_includes_entities():
    from app.telegram.commands import InlineButton

    route = respx.post("https://api.telegram.org/bottoken/sendMessage").mock(
        return_value=Response(200, json={"ok": True})
    )
    notifier = TelegramNotifier("token")
    notifier.send_with_buttons(1, "Model settings\n\n- Current default model: claude", [[InlineButton("claude", "/model claude")]])
    payload = json.loads(route.calls[0].request.content)
    assert payload["entities"][0] == {"type": "bold", "offset": 0, "length": len("Model settings")}
    assert payload["reply_markup"]["inline_keyboard"][0][0]["text"] == "claude"


@respx.mock
def test_notifier_single_line_message_has_no_entities():
    route = respx.post("https://api.telegram.org/bottoken/sendMessage").mock(
        return_value=Response(200, json={"ok": True})
    )
    notifier = TelegramNotifier("token")
    notifier.send_text(1, "plain line")
    payload = json.loads(route.calls[0].request.content)
    assert "entities" not in payload


@respx.mock
def test_notifier_long_text_applies_entities_to_first_chunk_only():
    route = respx.post("https://api.telegram.org/bottoken/sendMessage").mock(
        return_value=Response(200, json={"ok": True})
    )
    notifier = TelegramNotifier("token")
    job = Job(
        id="j-long",
        request=JobRequest(
            project="proj", model=ModelName.CLAUDE, instruction="x", chat_id=1, requested_by=1
        ),
        status=JobStatus.SUCCEEDED,
        branch="b",
        commit_hash="abc",
        changed_files=["a.py"],
        runner_stdout_summary="A" * 5000,
    )
    notifier.send_job_result(job)
    assert len(route.calls) >= 2
    first = json.loads(route.calls[0].request.content)
    second = json.loads(route.calls[1].request.content)
    assert "entities" in first
    assert "entities" not in second
