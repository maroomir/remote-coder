from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock

from app.jobs.plan_decisions import (
    PlanDecisionAnswer,
    PlanDecisionOption,
    PlanDecisionQuestion,
)
from app.jobs.schemas import JobRequest
from app.telegram.commands import InlineButton

PLAN_DECISION_CALLBACK_PREFIX = "__plan_dec__"
_BUTTON_LABEL_LIMIT = 60


@dataclass
class PendingPlanDecision:
    original_request: JobRequest
    original_text: str
    questions: list[PlanDecisionQuestion]
    answers: list[PlanDecisionAnswer] = field(default_factory=list)
    current_index: int = 0

    @property
    def is_complete(self) -> bool:
        return self.current_index >= len(self.questions)

    @property
    def current_question(self) -> PlanDecisionQuestion:
        return self.questions[self.current_index]


class PlanDecisionStore:
    def __init__(self) -> None:
        self._values: dict[tuple[str | None, int], PendingPlanDecision] = {}
        self._lock = Lock()

    def set(self, project_name: str | None, chat_id: int, pending: PendingPlanDecision) -> None:
        with self._lock:
            self._values[(project_name, chat_id)] = pending

    def get(self, project_name: str | None, chat_id: int) -> PendingPlanDecision | None:
        with self._lock:
            return self._values.get((project_name, chat_id))

    def pop(self, project_name: str | None, chat_id: int) -> PendingPlanDecision | None:
        with self._lock:
            return self._values.pop((project_name, chat_id), None)


def decision_callback_data(question_index: int, option_index: int) -> str:
    return f"{PLAN_DECISION_CALLBACK_PREFIX}:{question_index}:{option_index}"


def parse_decision_callback(data: str) -> tuple[int, int] | None:
    if not data.startswith(f"{PLAN_DECISION_CALLBACK_PREFIX}:"):
        return None
    parts = data.split(":")
    if len(parts) != 3:
        return None
    try:
        return int(parts[1]), int(parts[2])
    except ValueError:
        return None


def build_question_message(pending: PendingPlanDecision) -> tuple[str, list[list[InlineButton]]]:
    question = pending.current_question
    total = len(pending.questions)
    position = pending.current_index + 1
    lines = [f"❓ Decision {position}/{total}: {question.header}", "", question.question, ""]
    for option_index, option in enumerate(question.options, 1):
        if option.description:
            lines.append(f"{option_index}. {option.label} — {option.description}")
        else:
            lines.append(f"{option_index}. {option.label}")
    rows = [
        [
            InlineButton(
                _option_button_label(option),
                decision_callback_data(pending.current_index, option_index),
                style="primary" if option_index == 0 else None,
            )
        ]
        for option_index, option in enumerate(question.options)
    ]
    return "\n".join(lines), rows


def _option_button_label(option: PlanDecisionOption) -> str:
    label = option.label.strip()
    if len(label) > _BUTTON_LABEL_LIMIT:
        return f"{label[: _BUTTON_LABEL_LIMIT - 1].rstrip()}…"
    return label
