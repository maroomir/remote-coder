from pathlib import Path

import pytest

from app.admin.advanced_settings import AdvancedSettings, FileAdvancedSettingsStore
from app.models import UiLanguage
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
    text = ConversationContextBuilder.build(entries, "작업 시작해줘", UiLanguage.KOREAN)
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
    out = ConversationContextBuilder.build(entries, "go", UiLanguage.KOREAN)
    assert "...(truncated)" in out


def test_projects_isolated_by_name(tmp_path: Path):
    db = tmp_path / "iso.sqlite3"
    store = SQLiteConversationStore(db)
    store.append(project="a", chat_id=1, role="user", text="only-a", job_id=None)
    assert store.list_recent("b", 1, 10) == []


def test_delete_chat_memory_removes_only_project_and_chat(tmp_path: Path):
    db = tmp_path / "del_mem.sqlite3"
    store = SQLiteConversationStore(db)
    store.append(project="p1", chat_id=1, role="user", text="a", job_id=None)
    store.append(project="p1", chat_id=2, role="user", text="b", job_id=None)
    store.append(project="p2", chat_id=1, role="user", text="c", job_id=None)
    store.bind_message_branch(project="p1", chat_id=1, message_id=10, branch="remote-x", job_id="j1")

    entries, links = store.delete_chat_memory(project="p1", chat_id=1)
    assert entries >= 1
    assert links >= 1

    assert store.list_recent("p1", 1, 10) == []
    assert len(store.list_recent("p1", 2, 10)) == 1
    assert len(store.list_recent("p2", 1, 10)) == 1


def test_generate_report_uses_sql_aggregates(tmp_path: Path):
    db = tmp_path / "report.sqlite3"
    store = SQLiteConversationStore(db)
    store.append(project="p1", chat_id=10, role="user", text="README 수정", job_id=None)
    store.append(project="p1", chat_id=10, role="job_accepted", text="Job 접수: j1", job_id="j1")
    store.append(
        project="p1",
        chat_id=10,
        role="job_result",
        text="status=succeeded",
        job_id="j1",
    )
    report = store.generate_report("p1", 10, recent_limit=2)
    assert report is not None
    assert report.total_entries == 3
    assert report.count_for("user") == 1
    assert report.count_for("job_result") == 1
    assert report.latest_user_text == "README 수정"
    assert report.latest_job_id == "j1"
    assert report.latest_job_result == "status=succeeded"
    assert [entry.role for entry in report.recent_entries] == ["job_accepted", "job_result"]


def test_generate_report_returns_none_when_no_memory(tmp_path: Path):
    db = tmp_path / "empty_report.sqlite3"
    store = SQLiteConversationStore(db)
    assert store.generate_report("p1", 10) is None


def test_get_chat_stats_counts_roles(tmp_path: Path):
    db = tmp_path / "stats.sqlite3"
    store = SQLiteConversationStore(db)
    store.append(project="p1", chat_id=9, role="user", text="a", job_id=None)
    store.append(project="p1", chat_id=9, role="job_result", text="b", job_id="j1")
    stats = store.get_chat_stats("p1", 9)
    assert stats.total_rows == 2
    assert stats.rows_by_role["user"] == 1
    assert stats.rows_by_role["job_result"] == 1
    assert stats.db_path == db.resolve()
    assert stats.db_exists is True


def test_bind_message_branch_and_lookup(tmp_path: Path):
    db = tmp_path / "branch_link.sqlite3"
    store = SQLiteConversationStore(db)
    store.bind_message_branch(
        project="p1",
        chat_id=7,
        message_id=10,
        branch="remote-a",
        job_id="job-1",
    )

    assert store.get_bound_branch("p1", 7, 10) == "remote-a"
    assert store.get_bound_branch("p1", 7, 11) is None


def test_bind_user_message_job_allows_job_result_lookup_without_branch(tmp_path: Path):
    db = tmp_path / "user_job_link.sqlite3"
    store = SQLiteConversationStore(db)
    store.append(
        project="p1",
        chat_id=7,
        role="user",
        text="plan: outline reply context",
        message_id=10,
    )
    store.bind_user_message_job(
        project="p1",
        chat_id=7,
        message_id=10,
        job_id="job-plan-1",
    )
    store.append(
        project="p1",
        chat_id=7,
        role="job_result",
        text="status=succeeded stdout_preview=plan result",
        job_id="job-plan-1",
    )

    assert (
        store.get_latest_job_result_text_for_user_message("p1", 7, 10)
        == "status=succeeded stdout_preview=plan result"
    )


def test_format_job_context_includes_original_user_and_result_without_branch(tmp_path: Path):
    db = tmp_path / "job_context.sqlite3"
    store = SQLiteConversationStore(db)
    store.append(
        project="p1",
        chat_id=7,
        role="user",
        text="plan: 최초 계획 요청",
        job_id="job-plan-1",
        message_id=10,
    )
    store.append(
        project="p1",
        chat_id=7,
        role="job_result",
        text="status=succeeded stdout_preview=계획 결과",
        job_id="job-plan-1",
    )
    store.append(
        project="p2",
        chat_id=7,
        role="user",
        text="다른 프로젝트 맥락",
        job_id="job-plan-1",
        message_id=10,
    )

    ctx = store.format_job_context("p1", 7, "job-plan-1", UiLanguage.KOREAN)

    assert "[Reply Job 맥락]" in ctx
    assert "job_id=job-plan-1" in ctx
    assert "original_message_id: 10" in ctx
    assert "최초 계획 요청" in ctx
    assert "계획 결과" in ctx
    assert "다른 프로젝트 맥락" not in ctx


def test_format_job_context_uses_english_labels_by_default(tmp_path: Path):
    db = tmp_path / "job_context_en.sqlite3"
    store = SQLiteConversationStore(db)
    store.append(
        project="p1",
        chat_id=7,
        role="user",
        text="only English frame test",
        job_id="job-en-1",
        message_id=10,
    )
    store.append(
        project="p1",
        chat_id=7,
        role="job_result",
        text="ok",
        job_id="job-en-1",
    )
    ctx = store.format_job_context("p1", 7, "job-en-1")
    assert "[Reply job context]" in ctx
    assert "[/Reply job context]" in ctx
    assert "only English frame test" in ctx


def test_reply_to_recorded_bot_message_resolves_job_context(tmp_path: Path):
    db = tmp_path / "bot_reply_context.sqlite3"
    store = SQLiteConversationStore(db)
    store.append(
        project="p1",
        chat_id=7,
        role="user",
        text="plan: 최초 계획 요청",
        job_id="job-plan-1",
        message_id=10,
    )
    store.append(
        project="p1",
        chat_id=7,
        role="job_result",
        text="status=succeeded stdout_preview=계획 결과",
        job_id="job-plan-1",
        message_id=99,
    )

    ctx = store.format_reply_context("p1", 7, 99, UiLanguage.KOREAN)

    assert store.get_job_id_for_message_id("p1", 7, 99) == "job-plan-1"
    assert "[Reply Job 맥락]" in ctx
    assert "최초 계획 요청" in ctx
    assert "계획 결과" in ctx
    assert "job_history" in ctx


def test_sqlite_memory_limit_prunes_oldest_rows_globally(tmp_path: Path):
    adv = FileAdvancedSettingsStore(tmp_path / "advanced_settings.json")
    adv.save(
        AdvancedSettings(
            conversation_memory_limit_enabled=True,
            conversation_memory_max_rows=4,
            conversation_memory_max_bytes=None,
        )
    )
    db = tmp_path / "mem_rows.sqlite3"
    store = SQLiteConversationStore(db, advanced_settings_store=adv)
    for i in range(6):
        store.append(project="p", chat_id=1, role="user", text=f"x{i}", job_id=None)
    recent = store.list_recent("p", 1, 10)
    assert len(recent) == 4
    assert recent[0].text == "x2"


def test_sqlite_memory_limit_cleans_orphan_branch_links(tmp_path: Path):
    adv = FileAdvancedSettingsStore(tmp_path / "advanced_settings.json")
    adv.save(
        AdvancedSettings(
            conversation_memory_limit_enabled=True,
            conversation_memory_max_rows=3,
            conversation_memory_max_bytes=None,
        )
    )
    db = tmp_path / "mem_links.sqlite3"
    store = SQLiteConversationStore(db, advanced_settings_store=adv)
    store.append(project="p", chat_id=1, role="user", text="keep me", message_id=100, job_id=None)
    store.bind_message_branch(project="p", chat_id=1, message_id=100, branch="b1", job_id="j1")
    for i in range(5):
        store.append(project="p", chat_id=2, role="user", text=f"other{i}", job_id=None)
    assert store.get_bound_branch("p", 1, 100) is None


def test_format_reply_chain_context_and_collect_ids(tmp_path: Path):
    db = tmp_path / "reply_ctx.sqlite3"
    store = SQLiteConversationStore(db)
    store.append(
        project="p1",
        chat_id=1,
        role="user",
        text="msg A",
        message_id=10,
        reply_to_message_id=None,
    )
    store.bind_message_branch(
        project="p1",
        chat_id=1,
        message_id=10,
        branch="b-a",
        job_id="ja",
    )
    store.append(
        project="p1",
        chat_id=1,
        role="job_result",
        text="status=succeeded",
        job_id="ja",
    )
    store.append(
        project="p1",
        chat_id=1,
        role="user",
        text="msg B",
        message_id=20,
        reply_to_message_id=10,
    )
    store.bind_message_branch(
        project="p1",
        chat_id=1,
        message_id=20,
        branch="b-b",
        job_id="jb",
    )
    store.append(
        project="p1",
        chat_id=1,
        role="job_result",
        text="status=failed",
        job_id="jb",
    )

    ctx = store.format_reply_chain_context("p1", 1, reply_to_message_id=20, language=UiLanguage.KOREAN)
    assert "[Reply 체인 맥락]" in ctx
    assert "message_id=10" in ctx
    assert "message_id=20" in ctx
    assert "msg A" in ctx and "msg B" in ctx
    assert "status=succeeded" in ctx and "status=failed" in ctx

    ids = store.collect_reply_chain_message_ids("p1", 1, 20)
    assert ids == {10, 20}
