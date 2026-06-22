from app.jobs.diff_review import build_diff_review_summary
from app.jobs.schemas import Job, JobMode, JobRequest, JobStatus
from app.models import ModelName
from app.telegram.messages import build_job_result_message


def _succeeded_agent_job(diff_review=None) -> Job:
    job = Job(
        id="job-1",
        request=JobRequest(
            project="proj",
            model=ModelName.CLAUDE,
            instruction="do work",
            chat_id=1,
            requested_by=1,
            mode=JobMode.AGENT,
        ),
        status=JobStatus.SUCCEEDED,
        branch="remote-work",
        commit_hash="abc1234",
        changed_files=["app/foo.py", "poetry.lock"],
        diff_review=diff_review,
    )
    return job


def test_result_message_includes_review_card_with_impact_and_risk():
    review = build_diff_review_summary(
        [("app/foo.py", 10, 2), ("poetry.lock", 200, 0)]
    )
    job = _succeeded_agent_job(diff_review=review)

    text = build_job_result_message(job)

    assert "Review (2 files, +210/-2)" in text
    # Impact-ranked: lockfile (churn 200) listed before foo.py (churn 12).
    assert text.index("poetry.lock") < text.index("app/foo.py (+10/-2)")
    assert "⚠️ poetry.lock: dependency lockfile changed" in text


def test_result_message_without_review_card_when_absent():
    job = _succeeded_agent_job(diff_review=None)

    text = build_job_result_message(job)

    assert "Review (" not in text
    # The rest of the completed card is unchanged.
    assert "Job completed" in text
    assert "remote-work" in text


def test_korean_completed_message_renders_review_card_and_validation_block():
    # Regression: the Korean job.completed template must include the review-card and validation
    # placeholders, or features A and D render invisibly under Korean UI.
    from app.models import UiLanguage

    review = build_diff_review_summary([("poetry.lock", 200, 0)])
    job = _succeeded_agent_job(diff_review=review)
    job.commit_hash = None
    job.validation_failed = True
    job.validation_summary = "1 failed, 3 passed"

    korean = build_job_result_message(job).render(UiLanguage.KOREAN)

    assert "리뷰 (1개 파일" in korean
    assert "poetry.lock" in korean
    assert "검증 실패" in korean
    assert "1 failed, 3 passed" in korean
