import pytest

from app.jobs.schemas import Job, JobRequest
from app.models import ModelName


def test_job_status_transition_success():
    job = Job(
        id="j1",
        request=JobRequest(
            project="proj", model=ModelName.CLAUDE, instruction="x", chat_id=1, requested_by=1
        ),
    )
    job.mark_running()
    job.mark_succeeded()
    assert job.status.value == "succeeded"


def test_job_status_invalid_transition():
    job = Job(
        id="j1",
        request=JobRequest(
            project="proj", model=ModelName.CLAUDE, instruction="x", chat_id=1, requested_by=1
        ),
    )
    with pytest.raises(ValueError):
        job.mark_succeeded()
