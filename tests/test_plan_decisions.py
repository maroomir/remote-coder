from pathlib import Path
from unittest.mock import Mock

from app.ai.base import RunnerResult, instruction_for_runner_mode
from app.jobs.manager import JobManager
from app.jobs.plan_decisions import (
    PlanDecisionAnswer,
    PlanDecisionOption,
    PlanDecisionQuestion,
    compose_execute_plan_instruction,
    compose_phase_b_instruction,
    parse_plan_decisions,
)
from app.jobs.schemas import JobMode, JobRequest
from app.jobs.store import InMemoryJobStore
from app.models import ModelName

_BLOCK = """Here is my analysis.

```plan-decisions
{"questions": [
  {"id": "db", "header": "Database", "question": "Which database?",
   "options": [
     {"label": "PostgreSQL", "description": "Relational, robust"},
     {"label": "SQLite", "description": "Zero-config, file based"}
   ]}
]}
```
"""


def test_parse_plan_decisions_extracts_questions():
    questions = parse_plan_decisions(_BLOCK)
    assert questions is not None
    assert len(questions) == 1
    q = questions[0]
    assert q.id == "db"
    assert q.header == "Database"
    assert q.question == "Which database?"
    assert [o.label for o in q.options] == ["PostgreSQL", "SQLite"]


def test_parse_plan_decisions_returns_none_for_plain_plan():
    assert parse_plan_decisions("1. Do this\n2. Do that") is None


def test_parse_plan_decisions_returns_none_for_malformed_json():
    text = "```plan-decisions\n{not valid json}\n```"
    assert parse_plan_decisions(text) is None


def test_parse_plan_decisions_skips_question_with_too_few_options():
    text = (
        "```plan-decisions\n"
        '{"questions": [{"id": "x", "question": "Pick", '
        '"options": [{"label": "only"}]}]}\n'
        "```"
    )
    assert parse_plan_decisions(text) is None


def test_parse_plan_decisions_caps_at_three_questions():
    options = '[{"label": "a"}, {"label": "b"}]'
    items = ", ".join(
        f'{{"id": "q{i}", "question": "Q{i}", "options": {options}}}' for i in range(5)
    )
    text = f'```plan-decisions\n{{"questions": [{items}]}}\n```'
    questions = parse_plan_decisions(text)
    assert questions is not None
    assert len(questions) == 3


def test_compose_phase_b_instruction_embeds_answers():
    question = PlanDecisionQuestion(
        id="db",
        header="Database",
        question="Which database?",
        options=[PlanDecisionOption("PostgreSQL", "Relational")],
    )
    answers = [PlanDecisionAnswer(question=question, option=question.options[0])]
    text = compose_phase_b_instruction("Add persistence", answers)
    assert "Add persistence" in text
    assert "Which database?" in text
    assert "PostgreSQL" in text
    assert "Do not ask any more questions" in text


def test_compose_execute_plan_instruction_embeds_request_and_plan():
    text = compose_execute_plan_instruction("Add caching", "1. add a Cache class\n2. wire it up")
    assert "Add caching" in text
    assert "add a Cache class" in text
    assert "Implement the approved plan" in text


def test_plan_instruction_includes_decision_contract():
    wrapped = instruction_for_runner_mode("do work", JobMode.PLAN)
    assert "plan-decisions" in wrapped
    assert wrapped.endswith("do work")


def _plan_manager(test_settings, project_registry, stdout, router):
    store = InMemoryJobStore()
    git_service = Mock()
    git_service.prepare_detached_worktree.return_value = Path("/tmp/wt")
    factory = Mock()
    runner = Mock()
    runner.run.return_value = RunnerResult(
        exit_code=0, stdout=stdout, stderr="", started_at=None, finished_at=None
    )
    factory.create.return_value = runner
    notifier = Mock()
    manager = JobManager(
        test_settings,
        store,
        git_service,
        factory,
        Mock(),
        lambda _: notifier,
        project_registry,
        plan_decision_router=router,
    )
    return manager, notifier


def _plan_request(**overrides):
    base = dict(
        project="remote-coder",
        model=ModelName.CLAUDE,
        instruction="plan it",
        mode=JobMode.PLAN,
        chat_id=123,
        requested_by=123,
    )
    base.update(overrides)
    return JobRequest(**base)


def test_run_routes_plan_decisions_and_skips_result(test_settings, project_registry):
    routed = []
    manager, notifier = _plan_manager(
        test_settings, project_registry, _BLOCK, lambda job, qs: routed.append((job, qs)) or True
    )
    job = manager.submit(_plan_request())
    final = manager.run(job.id)

    assert final.status.value == "succeeded"
    assert len(routed) == 1
    assert len(routed[0][1]) == 1
    notifier.send_job_result.assert_not_called()


def test_run_without_decisions_sends_normal_result(test_settings, project_registry):
    routed = []
    manager, notifier = _plan_manager(
        test_settings, project_registry, "1. plain plan", lambda job, qs: routed.append(1) or True
    )
    job = manager.submit(_plan_request())
    manager.run(job.id)

    assert routed == []
    notifier.send_job_result.assert_called_once()


def test_run_skips_decisions_when_already_resolved(test_settings, project_registry):
    routed = []
    manager, notifier = _plan_manager(
        test_settings, project_registry, _BLOCK, lambda job, qs: routed.append(1) or True
    )
    job = manager.submit(_plan_request(plan_decisions_resolved=True))
    manager.run(job.id)

    assert routed == []
    notifier.send_job_result.assert_called_once()
