"""Characterization tests for app.git.commit_message.CommitMessageFormatter.

Tester 3 (AI Runners & Git Automation). These pin down current behavior for the
F6 auto-commit format and document heuristic edge cases. No production bug is
asserted here; the subject-length note is a Low-severity observation only.
"""

from __future__ import annotations

from app.git.commit_message import CommitMessageFormatter


def test_format_emits_type_title_bullets_and_trailer():
    message = CommitMessageFormatter.format(
        job_id="job_1",
        instruction="fix the login bug",
        changed_files=["app/auth.py"],
    )
    lines = message.splitlines()

    assert lines[0] == "fix: fix the login bug"
    assert lines[1] == ""
    assert lines[2].startswith("- AI agent")
    assert lines[-1] == "committed by remote-coder: job_1"


def test_empty_instruction_and_files_uses_safe_default():
    message = CommitMessageFormatter.format(job_id="job_2", instruction="", changed_files=[])
    assert message.startswith("feat: update requested behavior\n\n")
    assert "- AI agent implemented the requested change" in message


def test_all_chore_paths_force_chore_type_even_for_feature_instruction():
    # Documents the heuristic: when every changed file is a chore path the type
    # is `chore`, which can clash with a feature-sounding title.
    message = CommitMessageFormatter.format(
        job_id="job_3",
        instruction="add a shiny feature",
        changed_files=["README.md"],
    )
    assert message.splitlines()[0] == "chore: add a shiny feature"


def test_title_is_bounded_to_72_chars_but_subject_line_can_exceed_it():
    # PLAN.md F6 bounds the *title* (<= 72). The formatter caps the title text
    # at 72 but the full "type: title" subject line is not separately bounded,
    # so it can run past the 50-char human-commit guidance in AGENTS.md.
    long_instruction = (
        "Implement a brand new feature that does many things across the entire codebase today"
    )
    message = CommitMessageFormatter.format(
        job_id="job_4",
        instruction=long_instruction,
        changed_files=["app/x.py"],
    )
    subject = message.splitlines()[0]
    title = subject.split(": ", 1)[1]

    assert len(title) <= 72
    # Low-severity observation: the subject line itself exceeds 72 here.
    assert len(subject) > 72


def test_ai_title_over_72_chars_is_rejected_and_falls_back():
    # An AI-provided title longer than 72 chars is dropped in favor of the
    # instruction/scoped fallback, keeping the title bounded.
    message = CommitMessageFormatter.format(
        job_id="job_5",
        instruction="restructure the parser",
        changed_files=["app/parser.py"],
        ai_title="x" * 80,
    )
    title = message.splitlines()[0].split(": ", 1)[1]
    assert "x" * 80 not in title
    assert len(title) <= 72
