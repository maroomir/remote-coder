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


def test_commit_message_formatter_avoids_korean_prompt_as_title():
    instruction = (
        "src/utils 내 모든 소스코드에 대해 최신화된 AI AGENTS 규칙에 맞는 "
        "리팩토링 부탁드립니다. 모든 소스코드의 책임 경계를 다시 확인해주세요."
    )

    message = CommitMessageFormatter.format(
        job_id="job_20260510065204_74fa92",
        instruction=instruction,
        changed_files=["src/utils/path.py", "src/utils/text.py"],
    )

    assert message.startswith("refactor: refactor src/utils source\n\n")
    assert "부탁드립니다" not in message.splitlines()[0]
    assert "모든 소스코드" not in message.splitlines()[0]


def test_commit_message_formatter_rejects_ai_title_that_repeats_prompt():
    instruction = (
        "src/utils 내 모든 소스코드에 대해 최신화된 AI AGENTS 규칙에 맞는 "
        "리팩토링 부탁드립니다. 모든 소스코드의 책임 경계를 다시 확인해주세요."
    )

    message = CommitMessageFormatter.format(
        job_id="job_20260510065204_74fa92",
        instruction=instruction,
        changed_files=["src/utils/path.py"],
        ai_title=(
            "src/utils 내 모든 소스코드에 대해 최신화된 AI AGENTS 규칙에 맞는 "
            "리팩토링 부탁드립니다"
        ),
    )

    assert message.startswith("refactor: refactor src/utils source\n\n")
    assert "부탁드립니다" not in message.splitlines()[0]


def test_commit_message_formatter_skips_reply_job_context_block_for_title():
    instruction = (
        "[Reply job context]\n"
        "job_id=job_20260604224346_0794a6:\n"
        "  original_message_id: 635\n"
        "  original_user: ask: previous question text\n"
        "  job_result: status=succeeded model=gpt-5.5 stdout_preview=...\n"
        "  job_history:\n"
        "    - user message_id=635: ask: previous question text\n"
        "    - job_result message_id=639: status=succeeded\n"
        "[/Reply job context]\n"
        "\n"
        "Fix the broken commit automation so titles describe the change."
    )

    message = CommitMessageFormatter.format(
        job_id="job_20260604231739_fe1058",
        instruction=instruction,
        changed_files=["app/git/commit_message.py"],
    )

    title_line = message.splitlines()[0]
    assert "job_id=" not in title_line
    assert "original_user" not in title_line
    assert title_line.startswith("fix:")


def test_commit_message_formatter_extracts_current_request_inner_line():
    instruction = (
        "[Previous conversation/job context]\n"
        "user (job_id=job_20260601_aaaaaa): earlier conversation snippet\n"
        "[/previous context block]\n"
        "\n"
        "[Current request]\n"
        "fix the commit title selection bug\n"
        "[/current request]"
    )

    message = CommitMessageFormatter.format(
        job_id="job_20260604231739_fe1058",
        instruction=instruction,
        changed_files=["app/git/commit_message.py"],
    )

    title_line = message.splitlines()[0]
    assert title_line.startswith("fix:")
    assert "earlier conversation" not in title_line
