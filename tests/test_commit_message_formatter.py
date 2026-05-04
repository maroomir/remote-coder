from app.git.commit_message import CommitMessageFormatter


def test_commit_message_formatter_builds_remote_coder_template():
    message = CommitMessageFormatter.format(
        job_id="job_20260430010101_ab12cd",
        instruction="fix commit message format",
        changed_files=["app/jobs/manager.py", "tests/test_job_manager.py"],
    )

    assert message == (
        "fix: fix commit message format\n\n"
        "- AI agent fixed the requested behavior\n"
        "- AI agent updated automated coverage where applicable\n\n"
        "committed by remote-coder: job_20260430010101_ab12cd"
    )


def test_commit_message_formatter_uses_chore_for_docs_only_changes():
    message = CommitMessageFormatter.format(
        job_id="job_20260430010101_ab12cd",
        instruction="README 문서 업데이트",
        changed_files=["README.md", "docs/claude-guide.md"],
    )

    assert message.startswith("chore: README 문서 업데이트\n\n")
    assert "- AI agent refreshed related documentation where applicable\n" in message


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
        "feat: improve generated commit messages so commits clearly describe the added\n\n"
    )
    assert "00 project context" not in message
    assert "10 architecture oop gof" not in message


def test_commit_message_formatter_does_not_repeat_user_message():
    instruction = (
        "user: Monitor model 로 모델을 조회할 때, 현재 사용 모델(ex> ChatGPT 5.5 또는 "
        "Claude Opus 4.7 등등)과 토큰 사용량 등도 나오면"
    )

    message = CommitMessageFormatter.format(
        job_id="job_20260502215006_fa3889",
        instruction=instruction,
        changed_files=["app/monitoring/model.py", "tests/test_monitoring.py"],
    )

    assert message == (
        "feat: show current model and token usage in monitor model\n\n"
        "- AI agent implemented the requested change\n"
        "- AI agent updated automated coverage where applicable\n\n"
        "committed by remote-coder: job_20260502215006_fa3889"
    )
    assert "user: Monitor model" not in message
    assert "ChatGPT 5.5" not in message
    assert "Claude Opus" not in message
