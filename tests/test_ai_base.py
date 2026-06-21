from app.ai.base import instruction_for_runner_mode
from app.jobs.schemas import JobMode


def test_instruction_for_runner_mode_agent_unchanged():
    assert instruction_for_runner_mode("do work", JobMode.AGENT) == "do work"


def test_instruction_for_runner_mode_plan_prefix():
    out = instruction_for_runner_mode("refactor auth", JobMode.PLAN)
    assert "PLAN mode" in out
    assert "User request:" in out
    assert "refactor auth" in out


def test_instruction_for_runner_mode_ask_prefix():
    out = instruction_for_runner_mode("why X?", JobMode.ASK)
    assert "ASK mode" in out
    assert "User question:" in out
    assert "why X?" in out


def test_instruction_for_runner_mode_research_prefix():
    out = instruction_for_runner_mode("compare webhook security", JobMode.RESEARCH)
    assert "RESEARCH mode" in out
    assert "internet search" in out
    assert "source links" in out
    assert "compare webhook security" in out


# Golden byte-identity guards: the runner output for ASK/RESEARCH must stay exactly what it was
# before these modes moved to the data-driven ModeRegistry path. These pin literal bytes so a
# drift in either base.py or the registry seed is caught immediately.

_EXPECTED_ASK_PREFIX = (
    "You are in ASK mode. Analyze the codebase and answer the user's question. "
    "Do not modify files.\n\n"
    "User question:\n"
)

_EXPECTED_RESEARCH_PREFIX = (
    "You are in RESEARCH mode. Read the repository context and answer the user's research "
    "question. Do not modify files.\n\n"
    "Use internet search when it is useful or necessary for the question, similar to a deep "
    "research workflow. Compare multiple perspectives or sources when possible, and clearly "
    "separate repository-derived facts from external findings. Include citations or source "
    "links for external claims, call out uncertainty or limitations, and finish with a direct "
    "answer to the user's problem.\n\n"
    "User research request:\n"
)


def test_instruction_for_runner_mode_ask_byte_identity():
    assert (
        instruction_for_runner_mode("why X?", JobMode.ASK)
        == f"{_EXPECTED_ASK_PREFIX}why X?"
    )


def test_instruction_for_runner_mode_research_byte_identity():
    assert (
        instruction_for_runner_mode("compare options", JobMode.RESEARCH)
        == f"{_EXPECTED_RESEARCH_PREFIX}compare options"
    )


def test_instruction_for_runner_mode_unregistered_falls_through():
    assert instruction_for_runner_mode("raw text", "totally_unknown_mode") == "raw text"
