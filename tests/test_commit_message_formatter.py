from app.git.commit_message import CommitMessageFormatter


def test_commit_message_formatter_builds_remote_coder_template():
    message = CommitMessageFormatter.format(
        job_id="job_20260430010101_ab12cd",
        instruction="fix commit message format",
        changed_files=["app/jobs/manager.py", "tests/test_job_manager.py"],
    )

    assert message == (
        "fix: update job manager\n"
        "- update job manager and job manager tests\n"
        "- add or refresh automated coverage for the updated flow\n\n"
        "committed by remote-coder:job_20260430010101_ab12cd"
    )


def test_commit_message_formatter_uses_chore_for_docs_only_changes():
    message = CommitMessageFormatter.format(
        job_id="job_20260430010101_ab12cd",
        instruction="README 문서 업데이트",
        changed_files=["README.md", "docs/claude-guide.md"],
    )

    assert message.startswith("chore: update README and claude guide documentation\n")
    assert "- refresh related documentation for the new behavior\n" in message
