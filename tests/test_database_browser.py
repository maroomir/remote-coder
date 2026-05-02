from pathlib import Path

import pytest

from app.admin.database_browser import ConversationDatabaseBrowser
from app.telegram.conversation import SQLiteConversationStore


def test_browser_rejects_unknown_table():
    browser = ConversationDatabaseBrowser(Path("/tmp/will-not-open.sqlite3"))
    with pytest.raises(ValueError, match="unknown table"):
        browser.query_rows(
            "users",
            project=None,
            chat_id=None,
            role=None,
            job_id=None,
            q=None,
            sort="id",
            order="desc",
            limit=10,
            offset=0,
        )


def test_browser_missing_file_returns_empty_rows(tmp_path: Path):
    missing = tmp_path / "nope.sqlite3"
    browser = ConversationDatabaseBrowser(missing)
    out = browser.query_rows(
        "conversation_entries",
        project=None,
        chat_id=None,
        role=None,
        job_id=None,
        q=None,
        sort="id",
        order="desc",
        limit=10,
        offset=0,
    )
    assert out["total"] == 0
    assert out["rows"] == []


def test_browser_distinct_filter_options(tmp_path: Path):
    db = tmp_path / "fopt.sqlite3"
    store = SQLiteConversationStore(db)
    store.append(project="z", chat_id=1, role="user", text="a", job_id=None)
    store.append(project="z", chat_id=1, role="assistant", text="b", job_id=None)
    browser = ConversationDatabaseBrowser(db)
    d = browser.distinct_filter_options("conversation_entries")
    assert d["projects"] == ["z"]
    assert set(d["roles"]) == {"assistant", "user"}


def test_browser_iter_csv_includes_header_and_row(tmp_path: Path):
    db = tmp_path / "csv.sqlite3"
    store = SQLiteConversationStore(db)
    store.append(project="x", chat_id=1, role="user", text="a,b", job_id=None)
    browser = ConversationDatabaseBrowser(db)
    chunks = list(
        browser.iter_csv_rows(
            "conversation_entries",
            project="x",
            chat_id=1,
            role=None,
            job_id=None,
            q=None,
            sort="id",
            order="asc",
            max_rows=100,
            chunk_size=50,
        )
    )
    raw = b"".join(chunks).decode("utf-8")
    assert raw.startswith("\ufeff")
    assert "a,b" in raw


def test_browser_message_branch_links(tmp_path: Path):
    db = tmp_path / "c.sqlite3"
    store = SQLiteConversationStore(db)
    store.append(project="p", chat_id=1, role="user", text="x", job_id=None, message_id=10)
    store.bind_message_branch(project="p", chat_id=1, message_id=10, branch="feature/a", job_id="j1")
    browser = ConversationDatabaseBrowser(db)
    out = browser.query_rows(
        "message_branch_links",
        project="p",
        chat_id=1,
        role=None,
        job_id=None,
        q="feature",
        sort="branch",
        order="asc",
        limit=20,
        offset=0,
    )
    assert out["total"] == 1
    assert out["rows"][0]["branch"] == "feature/a"
