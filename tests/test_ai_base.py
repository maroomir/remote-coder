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
