from app.git.commit_message import CommitMessageFormatter


def test_commit_message_formatter_builds_remote_coder_template():
    message = CommitMessageFormatter.format(
        job_id="job_20260430010101_ab12cd",
        instruction="fix commit message format",
        changed_files=["app/jobs/manager.py", "tests/test_job_manager.py"],
    )

    assert message == (
        "fix: fix commit message format\n"
        "- implement requested behavior: fix commit message format\n"
        "- add or refresh automated coverage for the updated flow\n\n"
        "committed by remote-coder:job_20260430010101_ab12cd"
    )


def test_commit_message_formatter_uses_chore_for_docs_only_changes():
    message = CommitMessageFormatter.format(
        job_id="job_20260430010101_ab12cd",
        instruction="README 문서 업데이트",
        changed_files=["README.md", "docs/claude-guide.md"],
    )

    assert message.startswith("chore: README 문서 업데이트\n")
    assert "- refresh related documentation for the new behavior\n" in message


def test_commit_message_formatter_prefers_feature_intent_over_changed_file_list():
    message = CommitMessageFormatter.format(
        job_id="job_20260430010101_ab12cd",
        instruction="Improve generated commit messages so commits clearly describe the added feature",
        changed_files=[
            ".clinerules/00-project-context.md",
            ".clinerules/10-architecture-oop-gof.md",
            ".clinerules/20-tech-stack-and-fastapi.md",
            ".cursor/rules/00-project-context.mdc",
            "tests/test_commit_message_formatter.py",
        ],
    )

    assert message.startswith(
        "feat: improve generated commit messages so commits clearly describe the added\n"
    )
    assert "00 project context" not in message
    assert "10 architecture oop gof" not in message
