from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.jobs.schemas import FixKind, Job, JobMode, JobRequest, JobStatus
from app.jobs.store import InMemoryJobStore, SQLiteJobStore
from app.models import ModelName


def test_job_store_create_get_update():
    store = InMemoryJobStore()
    job = Job(
        id="id1",
        request=JobRequest(
            project="proj", model=ModelName.CLAUDE, instruction="i", chat_id=1, requested_by=1
        ),
    )
    store.create(job)
    fetched = store.get("id1")
    assert fetched is not None
    fetched.branch = "remote-1"
    store.update(fetched)
    assert store.get("id1").branch == "remote-1"


def test_get_latest_succeeded_branch_for_project_chat():
    store = InMemoryJobStore()
    t0 = datetime.now(UTC)
    old = Job(
        id="old",
        request=JobRequest(
            project="p", model=ModelName.CLAUDE, instruction="i", chat_id=5, requested_by=5
        ),
        status=JobStatus.SUCCEEDED,
        branch="remote-old",
        finished_at=t0,
    )
    new = Job(
        id="new",
        request=JobRequest(
            project="p", model=ModelName.CLAUDE, instruction="i", chat_id=5, requested_by=5
        ),
        status=JobStatus.SUCCEEDED,
        branch="remote-new",
        finished_at=t0 + timedelta(seconds=1),
    )
    store.create(old)
    store.create(new)
    assert store.get_latest_succeeded_branch_for_project_chat("p", 5) == "remote-new"
    assert store.get_latest_succeeded_branch_for_project_chat("p", 99) is None


def test_get_latest_succeeded_job_for_branch_returns_newest_match():
    store = InMemoryJobStore()
    t0 = datetime.now(UTC)
    old = Job(
        id="old",
        request=JobRequest(
            project="p", model=ModelName.CLAUDE, instruction="i", chat_id=5, requested_by=5
        ),
        status=JobStatus.SUCCEEDED,
        branch="remote-feature",
        commit_hash="aaa",
        finished_at=t0,
    )
    new = Job(
        id="new",
        request=JobRequest(
            project="p", model=ModelName.CLAUDE, instruction="i", chat_id=5, requested_by=5
        ),
        status=JobStatus.SUCCEEDED,
        branch="remote-feature",
        commit_hash="bbb",
        finished_at=t0 + timedelta(seconds=1),
    )
    store.create(old)
    store.create(new)

    job = store.get_latest_succeeded_job_for_branch("p", 5, "remote-feature")
    assert job is not None
    assert job.id == "new"
    assert store.get_latest_succeeded_job_for_branch("p", 5, "remote-missing") is None
    assert store.get_latest_succeeded_job_for_branch("p", 99, "remote-feature") is None


def test_sqlite_get_latest_succeeded_job_for_branch(tmp_path: Path):
    store = SQLiteJobStore(tmp_path / "jobs.sqlite3")
    job = Job(
        id="j",
        request=JobRequest(
            project="p", model=ModelName.CLAUDE, instruction="i", chat_id=7, requested_by=7
        ),
        status=JobStatus.SUCCEEDED,
        branch="remote-x",
        commit_hash="abc",
    )
    store.create(job)

    reopened = SQLiteJobStore(tmp_path / "jobs.sqlite3")
    fetched = reopened.get_latest_succeeded_job_for_branch("p", 7, "remote-x")
    assert fetched is not None
    assert fetched.id == "j"
    assert reopened.get_latest_succeeded_job_for_branch("p", 7, "remote-y") is None


def test_get_latest_succeeded_branch_for_project_chat_same_chat_different_projects():
    store = InMemoryJobStore()
    t0 = datetime.now(UTC)
    proj_a = Job(
        id="a",
        request=JobRequest(
            project="proj-a",
            model=ModelName.CLAUDE,
            instruction="i",
            chat_id=42,
            requested_by=42,
        ),
        status=JobStatus.SUCCEEDED,
        branch="remote-a",
        finished_at=t0,
    )
    proj_b = Job(
        id="b",
        request=JobRequest(
            project="proj-b",
            model=ModelName.CLAUDE,
            instruction="i",
            chat_id=42,
            requested_by=42,
        ),
        status=JobStatus.SUCCEEDED,
        branch="remote-b",
        finished_at=t0 + timedelta(seconds=1),
    )
    store.create(proj_a)
    store.create(proj_b)
    assert store.get_latest_succeeded_branch_for_project_chat("proj-a", 42) == "remote-a"
    assert store.get_latest_succeeded_branch_for_project_chat("proj-b", 42) == "remote-b"


def test_list_succeeded_branches_for_project_chat_filters_orders_and_deduplicates():
    store = InMemoryJobStore()
    base = datetime.now(UTC)

    def add(
        job_id: str,
        branch: str | None,
        *,
        project: str = "p",
        chat_id: int = 5,
        status: JobStatus = JobStatus.SUCCEEDED,
        offset: int = 0,
    ) -> None:
        store.create(
            Job(
                id=job_id,
                request=JobRequest(
                    project=project,
                    model=ModelName.CLAUDE,
                    instruction="i",
                    chat_id=chat_id,
                    requested_by=chat_id,
                ),
                status=status,
                branch=branch,
                created_at=base + timedelta(seconds=offset),
                finished_at=base + timedelta(seconds=offset),
            )
        )

    add("old", "remote-shared", offset=1)
    add("new", "remote-new", offset=4)
    add("shared-new", "remote-shared", offset=3)
    add("failed", "remote-failed", status=JobStatus.FAILED, offset=6)
    add("other-chat", "remote-other-chat", chat_id=9, offset=7)
    add("other-project", "remote-other-project", project="q", offset=8)
    add("no-branch", None, offset=9)

    assert store.list_succeeded_branches_for_project_chat("p", 5) == [
        "remote-new",
        "remote-shared",
    ]


def test_list_recent_for_chat_filters_by_chat():
    store = InMemoryJobStore()
    old = Job(
        id="old",
        request=JobRequest(
            project="p", model=ModelName.CLAUDE, instruction="i", chat_id=5, requested_by=5
        ),
        created_at=datetime.now(UTC),
    )
    other = Job(
        id="other",
        request=JobRequest(
            project="p", model=ModelName.CLAUDE, instruction="i", chat_id=99, requested_by=99
        ),
        created_at=old.created_at + timedelta(seconds=1),
    )
    new = Job(
        id="new",
        request=JobRequest(
            project="p", model=ModelName.CLAUDE, instruction="i", chat_id=5, requested_by=5
        ),
        created_at=old.created_at + timedelta(seconds=2),
    )
    store.create(old)
    store.create(other)
    store.create(new)

    assert [job.id for job in store.list_recent_for_chat(5)] == ["new", "old"]


def test_list_recent_for_project_chat_filters_project_and_chat():
    store = InMemoryJobStore()
    base = datetime.now(UTC)
    same_chat_other_proj = Job(
        id="other-proj",
        request=JobRequest(
            project="other",
            model=ModelName.CLAUDE,
            instruction="i",
            chat_id=5,
            requested_by=5,
        ),
        created_at=base + timedelta(seconds=3),
    )
    same_proj_other_chat = Job(
        id="other-chat",
        request=JobRequest(
            project="p",
            model=ModelName.CLAUDE,
            instruction="i",
            chat_id=99,
            requested_by=99,
        ),
        created_at=base + timedelta(seconds=2),
    )
    match_old = Job(
        id="match-old",
        request=JobRequest(
            project="p",
            model=ModelName.CLAUDE,
            instruction="i",
            chat_id=5,
            requested_by=5,
        ),
        created_at=base,
    )
    match_new = Job(
        id="match-new",
        request=JobRequest(
            project="p",
            model=ModelName.CLAUDE,
            instruction="i",
            chat_id=5,
            requested_by=5,
        ),
        created_at=base + timedelta(seconds=1),
    )
    store.create(match_old)
    store.create(match_new)
    store.create(same_proj_other_chat)
    store.create(same_chat_other_proj)

    assert [job.id for job in store.list_recent_for_project_chat("p", 5)] == ["match-new", "match-old"]


def test_list_latest_by_status_filters_latest_jobs_in_created_order():
    store = InMemoryJobStore()
    base = datetime.now(UTC)
    older_queued = Job(
        id="older",
        request=JobRequest(
            project="p", model=ModelName.CLAUDE, instruction="old", chat_id=1, requested_by=1
        ),
        status=JobStatus.QUEUED,
        created_at=base,
    )
    newer_running = Job(
        id="newer",
        request=JobRequest(
            project="p", model=ModelName.CLAUDE, instruction="new", chat_id=1, requested_by=1
        ),
        status=JobStatus.RUNNING,
        created_at=base + timedelta(seconds=1),
    )
    superseded = Job(
        id="same",
        request=JobRequest(
            project="p", model=ModelName.CLAUDE, instruction="queued", chat_id=1, requested_by=1
        ),
        status=JobStatus.QUEUED,
        created_at=base + timedelta(seconds=2),
    )
    latest = Job(
        id="same",
        request=JobRequest(
            project="p", model=ModelName.CLAUDE, instruction="done", chat_id=1, requested_by=1
        ),
        status=JobStatus.SUCCEEDED,
        created_at=base + timedelta(seconds=3),
    )
    store.create(older_queued)
    store.create(newer_running)
    store.create(superseded)
    store.create(latest)

    assert [
        job.id for job in store.list_latest_by_status([JobStatus.QUEUED, JobStatus.RUNNING])
    ] == ["older", "newer"]


def test_sqlite_job_store_persists_jobs_across_instances(tmp_path: Path):
    db_path = tmp_path / "jobs.sqlite3"
    store = SQLiteJobStore(db_path)
    t0 = datetime.now(UTC)
    job = Job(
        id="job-persist",
        request=JobRequest(
            project="p",
            model=ModelName.CODEX,
            instruction="fix persisted job store",
            mode=JobMode.AGENT_FIX,
            chat_id=5,
            requested_by=5,
            message_id=10,
            reply_to_message_id=9,
            parent_job_id="parent",
            fix_kind=FixKind.SOURCE,
        ),
        status=JobStatus.SUCCEEDED,
        branch="remote-persist",
        commit_hash="abc123",
        changed_files=["app/jobs/store.py"],
        runner_actual_model="gpt-5.5",
        runner_token_usage={"input": 100, "output": 25, "total": 125},
        accepted_message_id=11,
        result_message_ids=[12, 13],
        created_at=t0,
        started_at=t0 + timedelta(seconds=1),
        finished_at=t0 + timedelta(seconds=2),
        log_path=tmp_path / "job.log",
    )
    store.create(job)

    reopened = SQLiteJobStore(db_path)
    fetched = reopened.get("job-persist")

    assert fetched == job
    assert reopened.get_latest_succeeded_branch_for_project_chat("p", 5) == "remote-persist"
    assert reopened.list_succeeded_branches_for_project_chat("p", 5) == ["remote-persist"]
    assert [item.id for item in reopened.list_recent_for_project_chat("p", 5)] == ["job-persist"]


def test_sqlite_list_succeeded_branches_is_latest_first_and_unique(tmp_path: Path):
    db_path = tmp_path / "jobs.sqlite3"
    store = SQLiteJobStore(db_path)
    base = datetime.now(UTC)
    for job_id, branch, offset in (
        ("old-shared", "remote-shared", 1),
        ("new", "remote-new", 3),
        ("new-shared", "remote-shared", 2),
    ):
        store.create(
            Job(
                id=job_id,
                request=JobRequest(
                    project="p",
                    model=ModelName.CLAUDE,
                    instruction="i",
                    chat_id=5,
                    requested_by=5,
                ),
                status=JobStatus.SUCCEEDED,
                branch=branch,
                created_at=base + timedelta(seconds=offset),
                finished_at=base + timedelta(seconds=offset),
            )
        )

    reopened = SQLiteJobStore(db_path)
    assert reopened.list_succeeded_branches_for_project_chat("p", 5) == [
        "remote-new",
        "remote-shared",
    ]


def test_sqlite_job_store_keeps_multiple_runs_for_reused_job_id(tmp_path: Path):
    store = SQLiteJobStore(tmp_path / "jobs.sqlite3")
    first = Job(
        id="same",
        request=JobRequest(
            project="p",
            model=ModelName.CLAUDE,
            instruction="first",
            chat_id=1,
            requested_by=1,
        ),
        created_at=datetime.now(UTC),
    )
    second = Job(
        id="same",
        request=JobRequest(
            project="p",
            model=ModelName.CLAUDE,
            instruction="second",
            chat_id=1,
            requested_by=1,
        ),
        created_at=first.created_at + timedelta(seconds=1),
    )
    store.create(first)
    store.create(second)

    assert store.get("same") == second
    assert [job.request.instruction for job in store.list_recent(10)[:2]] == ["second", "first"]


def test_sqlite_list_latest_by_status_filters_latest_rows(tmp_path: Path):
    store = SQLiteJobStore(tmp_path / "jobs.sqlite3")
    base = datetime.now(UTC)
    jobs = [
        Job(
            id="queued-old",
            request=JobRequest(
                project="p",
                model=ModelName.CLAUDE,
                instruction="old",
                chat_id=1,
                requested_by=1,
            ),
            status=JobStatus.QUEUED,
            created_at=base,
        ),
        Job(
            id="running-new",
            request=JobRequest(
                project="p",
                model=ModelName.CLAUDE,
                instruction="run",
                chat_id=1,
                requested_by=1,
            ),
            status=JobStatus.RUNNING,
            created_at=base + timedelta(seconds=1),
        ),
        Job(
            id="same",
            request=JobRequest(
                project="p",
                model=ModelName.CLAUDE,
                instruction="queued",
                chat_id=1,
                requested_by=1,
            ),
            status=JobStatus.QUEUED,
            created_at=base + timedelta(seconds=2),
        ),
        Job(
            id="same",
            request=JobRequest(
                project="p",
                model=ModelName.CLAUDE,
                instruction="done",
                chat_id=1,
                requested_by=1,
            ),
            status=JobStatus.SUCCEEDED,
            created_at=base + timedelta(seconds=3),
        ),
    ]
    for job in jobs:
        store.create(job)

    reopened = SQLiteJobStore(tmp_path / "jobs.sqlite3")

    assert [
        job.id for job in reopened.list_latest_by_status([JobStatus.QUEUED, JobStatus.RUNNING])
    ] == ["queued-old", "running-new"]
