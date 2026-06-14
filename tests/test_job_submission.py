from unittest.mock import Mock

from app.jobs.schemas import Job, JobRequest, JobStatus
from app.models import ModelName
from app.telegram.conversation import SQLiteConversationStore
from app.telegram.handlers.job_submission import JobSubmission


def test_record_final_job_result_persists_memory_session_and_branch(tmp_path):
    store = SQLiteConversationStore(tmp_path / "conversation.sqlite3")
    persisted: list[str] = []
    submission = JobSubmission(
        job_manager=Mock(),
        conversation_store=store,
        attach_session=lambda _request: None,
        persist_session_token=lambda job: persisted.append(job.runner_session_id or ""),
    )
    job = Job(
        id="job-1",
        request=JobRequest(
            project="p",
            model=ModelName.CLAUDE,
            instruction="x",
            chat_id=7,
            requested_by=7,
            message_id=10,
            session_id="session-1",
        ),
        status=JobStatus.SUCCEEDED,
        branch="remote-fix",
        commit_hash="abc123",
        runner_session_id="runner-1",
        result_message_ids=[22],
    )

    submission.record_final_job_result(job)

    report = store.generate_report(project="p", chat_id=7, recent_limit=5)
    assert report is not None
    assert persisted == ["runner-1"]
    assert report.count_for("job_result") == 1
    assert report.latest_job_result is not None
    assert "status=succeeded" in report.latest_job_result
    assert store.get_bound_branch("p", 7, 10) == "remote-fix"
