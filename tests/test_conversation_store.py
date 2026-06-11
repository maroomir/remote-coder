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


@pytest.mark.parametrize("size", [900, 2500])
def test_context_builder_keeps_entries_within_default_limit(size: int):
    long_text = "x" * size
    entries = [
        ConversationEntry(id=1, project="p", chat_id=1, role="user", text=long_text, job_id=None),
    ]
    out = ConversationContextBuilder.build(entries, "go", UiLanguage.KOREAN)
    assert "...(truncated)" not in out


def test_context_builder_truncates_long_entry():
    long_text = "x" * 3500
    entries = [
        ConversationEntry(id=1, project="p", chat_id=1, role="user", text=long_text, job_id=None),
    ]
    out = ConversationContextBuilder.build(entries, "go", UiLanguage.KOREAN)
    assert "...(truncated)" in out


def test_context_builder_respects_custom_snippet_limit(tmp_path: Path):
    long_text = "x" * 1500
    entries = [
        ConversationEntry(id=1, project="p", chat_id=1, role="user", text=long_text, job_id=None),
    ]
    out = ConversationContextBuilder.build(entries, "go", UiLanguage.KOREAN, snippet_max_chars=1000)
    assert "...(truncated)" in out


def test_format_job_context_truncates_long_text_at_default_snippet_limit(tmp_path: Path):
    db = tmp_path / "job_context_trunc.sqlite3"
    store = SQLiteConversationStore(db)
    long_user = "u" * 3500
    long_result = "r" * 3500
    store.append(
        project="p1",
        chat_id=7,
        role="user",
        text=long_user,
        job_id="job-long",
        message_id=10,
    )
    store.append(
        project="p1",
        chat_id=7,
        role="job_result",
        text=long_result,
        job_id="job-long",
    )

    ctx = store.format_job_context("p1", 7, "job-long", UiLanguage.ENGLISH)

    assert "...(truncated)" in ctx
    assert long_user not in ctx
    assert long_result not in ctx


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


def _seed_user(store, *, chat_id, message_id, job_id, reply_to=None, text="msg"):
    store.append(
        project="p1",
        chat_id=chat_id,
        role="user",
        text=text,
        job_id=job_id,
        message_id=message_id,
        reply_to_message_id=reply_to,
    )


def _seed_result(store, *, chat_id, message_id, job_id):
    store.append(
        project="p1",
        chat_id=chat_id,
        role="job_result",
        text="status=succeeded",
        job_id=job_id,
        message_id=message_id,
    )


def test_resolve_session_reply_chain_shares_root_session(tmp_path: Path):
    store = SQLiteConversationStore(tmp_path / "sess.sqlite3")

    # M1 -> S1, M2 -> S2 (independent roots)
    _seed_user(store, chat_id=1, message_id=101, job_id="j1")
    s1 = store.resolve_or_create_session("p1", 1, 101, None)
    _seed_user(store, chat_id=1, message_id=102, job_id="j2")
    s2 = store.resolve_or_create_session("p1", 1, 102, None)

    # Agent replies R1, R2 carry the originating job ids.
    _seed_result(store, chat_id=1, message_id=201, job_id="j1")
    _seed_result(store, chat_id=1, message_id=202, job_id="j2")

    # M3 replies to the M1 user message -> same session as S1.
    _seed_user(store, chat_id=1, message_id=103, job_id="j3", reply_to=101)
    s3 = store.resolve_or_create_session("p1", 1, 103, 101)

    # M4 replies to R2 (an agent message) -> resolves through job j2 back to S2.
    _seed_user(store, chat_id=1, message_id=104, job_id="j4", reply_to=202)
    s4 = store.resolve_or_create_session("p1", 1, 104, 202)

    assert s1 != s2
    assert s3 == s1
    assert s4 == s2


def test_resolve_session_is_stable_for_same_message(tmp_path: Path):
    store = SQLiteConversationStore(tmp_path / "sess2.sqlite3")
    _seed_user(store, chat_id=1, message_id=10, job_id="j1")
    first = store.resolve_or_create_session("p1", 1, 10, None)
    second = store.resolve_or_create_session("p1", 1, 10, None)
    assert first == second


def test_runner_resume_token_roundtrip(tmp_path: Path):
    store = SQLiteConversationStore(tmp_path / "tok.sqlite3")
    assert store.get_runner_resume_token("s1", "claude") is None
    store.set_runner_resume_token("s1", "claude", "tok-a")
    assert store.get_runner_resume_token("s1", "claude") == "tok-a"
    store.set_runner_resume_token("s1", "claude", "tok-b")
    assert store.get_runner_resume_token("s1", "claude") == "tok-b"
    # Providers are tracked independently.
    assert store.get_runner_resume_token("s1", "codex") is None
    store.set_runner_resume_token("s1", "codex", "codex-tok")
    assert store.get_runner_resume_token("s1", "codex") == "codex-tok"
    assert store.get_runner_resume_token("s1", "claude") == "tok-b"


def test_get_chat_stats_counts_sessions(tmp_path: Path):
    store = SQLiteConversationStore(tmp_path / "stats_sessions.sqlite3")
    _seed_user(store, chat_id=1, message_id=10, job_id="j1")
    assert store.get_chat_stats("p1", 1).session_count == 0
    store.resolve_or_create_session("p1", 1, 10, None)
    assert store.get_chat_stats("p1", 1).session_count == 1


def test_delete_chat_memory_clears_sessions(tmp_path: Path):
    store = SQLiteConversationStore(tmp_path / "clr.sqlite3")
    _seed_user(store, chat_id=1, message_id=10, job_id="j1")
    session = store.resolve_or_create_session("p1", 1, 10, None)
    store.set_runner_resume_token(session, "claude", "tok")

    store.delete_chat_memory(project="p1", chat_id=1)

    assert store.get_runner_resume_token(session, "claude") is None
    _seed_user(store, chat_id=1, message_id=10, job_id="j1")
    new_session = store.resolve_or_create_session("p1", 1, 10, None)
    assert new_session != session
