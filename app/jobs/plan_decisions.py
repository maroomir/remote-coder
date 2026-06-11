from __future__ import annotations

import json
import re
from dataclasses import dataclass

_MAX_QUESTIONS = 3
_MIN_OPTIONS = 2
_MAX_OPTIONS = 4

# Callback data prefix for the "Run plan" button attached to a successful PLAN result.
PLAN_EXECUTE_CALLBACK_PREFIX = "__plan_exec__"

# The PLAN-phase model emits decisions inside a fenced ```plan-decisions block (see
# instruction_for_runner_mode). Match the first such block anywhere in the output.
_DECISIONS_BLOCK_PATTERN = re.compile(
    r"```plan-decisions\s*\n(?P<body>.*?)\n```",
    re.DOTALL | re.IGNORECASE,
)


@dataclass(frozen=True)
class PlanDecisionOption:
    label: str
    description: str


@dataclass(frozen=True)
class PlanDecisionQuestion:
    id: str
    header: str
    question: str
    options: list[PlanDecisionOption]


@dataclass(frozen=True)
class PlanDecisionAnswer:
    question: PlanDecisionQuestion
    option: PlanDecisionOption


def _coerce_option(raw: object) -> PlanDecisionOption | None:
    if not isinstance(raw, dict):
        return None
    label = raw.get("label")
    if not isinstance(label, str) or not label.strip():
        return None
    description = raw.get("description")
    description = description if isinstance(description, str) else ""
    return PlanDecisionOption(label=label.strip(), description=description.strip())


def _coerce_question(raw: object) -> PlanDecisionQuestion | None:
    if not isinstance(raw, dict):
        return None
    question = raw.get("question")
    if not isinstance(question, str) or not question.strip():
        return None
    options: list[PlanDecisionOption] = []
    for raw_option in raw.get("options", []) or []:
        option = _coerce_option(raw_option)
        if option is not None:
            options.append(option)
    if not (_MIN_OPTIONS <= len(options) <= _MAX_OPTIONS):
        return None
    qid = raw.get("id")
    qid = qid.strip() if isinstance(qid, str) and qid.strip() else question.strip()[:32]
    header = raw.get("header")
    header = header.strip() if isinstance(header, str) and header.strip() else "Decision"
    return PlanDecisionQuestion(
        id=qid,
        header=header[:24],
        question=question.strip(),
        options=options,
    )


def parse_plan_decisions(stdout: str) -> list[PlanDecisionQuestion] | None:
    """Extract decision questions from a PLAN runner's raw stdout.

    Returns the validated questions when the model emitted a well-formed
    ```plan-decisions block, otherwise None so callers fall back to delivering the
    output as an ordinary plan.
    """
    if not stdout:
        return None
    match = _DECISIONS_BLOCK_PATTERN.search(stdout)
    if match is None:
        return None
    try:
        payload = json.loads(match.group("body"))
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    questions: list[PlanDecisionQuestion] = []
    for raw_question in payload.get("questions", []) or []:
        parsed = _coerce_question(raw_question)
        if parsed is not None:
            questions.append(parsed)
        if len(questions) >= _MAX_QUESTIONS:
            break
    return questions or None


def compose_execute_plan_instruction(original_instruction: str, plan_text: str) -> str:
    """Build the AGENT instruction that implements an approved PLAN result."""
    return "\n".join(
        [
            "[Original request]",
            original_instruction.strip(),
            "",
            "[Approved plan]",
            plan_text.strip(),
            "",
            "Implement the approved plan above. Make the code changes it describes; do not "
            "re-plan or ask for further decisions.",
        ]
    )


def compose_phase_b_instruction(
    original_instruction: str,
    answers: list[PlanDecisionAnswer],
) -> str:
    """Build the phase-B PLAN instruction with the user's decisions injected."""
    lines = [
        "[Original request]",
        original_instruction.strip(),
        "",
        "[Decisions already made by the user]",
    ]
    for index, answer in enumerate(answers, 1):
        lines.append(f"{index}. {answer.question.question}")
        chosen = f"   -> {answer.option.label}"
        if answer.option.description:
            chosen += f" ({answer.option.description})"
        lines.append(chosen)
    lines.extend(
        [
            "",
            "These decisions are final. Do not ask any more questions and do not output a "
            "plan-decisions block. Produce the concrete change plan that reflects the decisions "
            "above.",
        ]
    )
    return "\n".join(lines)
