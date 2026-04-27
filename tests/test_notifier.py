import respx
from httpx import Response

from app.jobs.schemas import Job, JobRequest, JobStatus
from app.models import ModelName
from app.telegram.notifier import TelegramNotifier


@respx.mock
def test_notifier_send_job_result_success():
    route = respx.post("https://api.telegram.org/bottoken/sendMessage").mock(
        return_value=Response(200, json={"ok": True})
    )
    notifier = TelegramNotifier("token")
    job = Job(
        id="j1",
        request=JobRequest(
            project="proj", model=ModelName.CLAUDE, instruction="x", chat_id=1, requested_by=1
        ),
        status=JobStatus.SUCCEEDED,
        branch="b",
        commit_hash="abc",
        changed_files=["a.py"],
    )
    notifier.send_job_result(job)
    assert route.called
