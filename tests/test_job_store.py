from datetime import UTC, datetime, timedelta

from app.jobs.schemas import Job, JobRequest, JobStatus
from app.jobs.store import InMemoryJobStore
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
