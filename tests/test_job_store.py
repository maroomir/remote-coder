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


def test_get_latest_succeeded_branch_for_chat():
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
    assert store.get_latest_succeeded_branch_for_chat(5) == "remote-new"
    assert store.get_latest_succeeded_branch_for_chat(99) is None
