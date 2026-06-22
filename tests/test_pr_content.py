from app.jobs.diff_review import build_diff_review_summary
from app.jobs.pr_content import build_pr_body
from app.jobs.schemas import Job, JobRequest, JobStatus
from app.models import ModelName


def _succeeded_job(diff_review=None, runner_actual_model=None) -> Job:
    return Job(
        id="job-1",
        request=JobRequest(
            project="proj",
            model=ModelName.CLAUDE,
            instruction="fix login",
            chat_id=1,
            requested_by=1,
        ),
        status=JobStatus.SUCCEEDED,
        branch="remote-fix-login",
        commit_hash="abc1234",
        runner_actual_model=runner_actual_model,
        diff_review=diff_review,
    )


def test_body_without_job_falls_back_to_branch_and_limitations():
    body = build_pr_body("remote-x", requests=[], job=None)

    assert "Work branch: `remote-x`" in body
    assert "## Known limitations" in body
    assert "Automated tests were not run" in body
    assert "## Change summary" not in body
    assert "**Model:**" not in body


def test_body_includes_model_and_change_summary_from_job():
    review = build_diff_review_summary([("app/foo.py", 10, 2), ("poetry.lock", 200, 0)])
    job = _succeeded_job(diff_review=review, runner_actual_model="Claude Sonnet 4.5")

    body = build_pr_body(
        "remote-fix-login",
        requests=[("fix the login bug", "done")],
        job=job,
    )

    assert "**Model:** Claude Sonnet 4.5" in body
    assert "## Work request" in body
    assert "**Request:** fix the login bug" in body
    assert "## Change summary (2 files, +210/-2)" in body
    assert "`poetry.lock` (+200/-0)" in body
    # Risk flags surface as known limitations for the reviewer.
    assert "Risk: poetry.lock: dependency lockfile changed" in body


def test_body_uses_ascii_fallback_for_non_ascii_requests():
    job = _succeeded_job()

    body = build_pr_body(
        "remote-x",
        requests=[("로그인 고쳐줘", "수정 완료")],
        job=job,
    )

    assert "로그인" not in body
    assert "수정 완료" not in body
    assert "Request omitted because it contains non-ASCII text." in body
    assert "AI result omitted because it contains non-ASCII text." in body


def test_multiple_requests_are_numbered():
    body = build_pr_body(
        "remote-x",
        requests=[("first", "r1"), ("second", "r2")],
        job=None,
    )

    assert "### Request 1" in body
    assert "### Request 2" in body
    assert "**Request:** first" in body
    assert "**Request:** second" in body
