from app.jobs.schemas import Job, JobRequest
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
