from pathlib import Path

import pytest

from app.telegram.conversation import (
    ConversationContextBuilder,
    ConversationEntry,
    SQLiteConversationStore,
    is_ambiguous_followup,
)


def test_is_ambiguous_followup():
    assert is_ambiguous_followup("작업 시작해줘")
    assert is_ambiguous_followup("  진행해줘  ")
    assert not is_ambiguous_followup("fix login bug")


def test_sqlite_store_append_and_list_recent(tmp_path: Path):
    db = tmp_path / "conv.sqlite3"
    store = SQLiteConversationStore(db)
    store.append(project="p1", chat_id=1, role="user", text="hello", job_id=None)
    store.append(project="p1", chat_id=1, role="job_accepted", text="Job 접수: j1", job_id="j1")
    store.append(project="p1", chat_id=2, role="user", text="other chat", job_id=None)
    recent = store.list_recent("p1", chat_id=1, limit=10)
    assert len(recent) == 2
    assert recent[0].role == "user" and recent[0].text == "hello"
    assert recent[1].job_id == "j1"


def test_sqlite_store_list_recent_respects_limit(tmp_path: Path):
    db = tmp_path / "c2.sqlite3"
    store = SQLiteConversationStore(db)
    for i in range(5):
        store.append(project="p", chat_id=1, role="user", text=f"m{i}", job_id=None)
    recent = store.list_recent("p", 1, limit=3)
    assert len(recent) == 3
    assert recent[0].text == "m2"
    assert recent[1].text == "m3"
    assert recent[2].text == "m4"


def test_context_builder_includes_sections():
    entries = [
        ConversationEntry(id=1, project="p", chat_id=1, role="user", text="prior", job_id=None),
    ]
    text = ConversationContextBuilder.build(entries, "작업 시작해줘")
    assert "[이전 대화/작업 맥락]" in text
    assert "[현재 요청]" in text
    assert "prior" in text
    assert "작업 시작해줘" in text


@pytest.mark.parametrize("size", [900, 1200])
def test_context_builder_truncates_long_entry(size: int):
    long_text = "x" * size
    entries = [
        ConversationEntry(id=1, project="p", chat_id=1, role="user", text=long_text, job_id=None),
    ]
    out = ConversationContextBuilder.build(entries, "go")
    assert "...(truncated)" in out


def test_projects_isolated_by_name(tmp_path: Path):
    db = tmp_path / "iso.sqlite3"
    store = SQLiteConversationStore(db)
    store.append(project="a", chat_id=1, role="user", text="only-a", job_id=None)
    assert store.list_recent("b", 1, 10) == []
