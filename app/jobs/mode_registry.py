from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

from app.jobs.schemas import JobMode

# Prompt prefixes prepended to the user instruction. These MUST stay byte-identical to the
# branches in app.ai.base.instruction_for_runner_mode; tests/test_mode_registry.py asserts the
# equality so the two sources cannot silently drift before the later integration phase.
_PLAN_PROMPT = (
    "You are in PLAN mode. Read the codebase and produce a concrete change plan. "
    "Do not modify files.\n\n"
    "Before finalizing, decide whether the plan depends on choices only the user can make "
    "(for example: which library/database to use, reuse an existing module vs. create a new one, "
    "scope or behavior trade-offs). If such open decisions exist, do NOT write the plan yet. "
    "Instead output ONLY a single fenced block exactly like this and nothing else:\n"
    "```plan-decisions\n"
    '{"questions": [{"id": "short_id", "header": "Short label", '
    '"question": "The decision to make?", "options": ['
    '{"label": "Option A", "description": "What this choice means"}, '
    '{"label": "Option B", "description": "What this choice means"}]}]}\n'
    "```\n"
    "Rules for the block: at most 3 questions; each question has 2-4 options; keep labels short "
    "and descriptions to one sentence; valid JSON only. If there are no genuine open decisions, "
    "skip the block entirely and just write the plan as usual.\n\n"
    "User request:\n"
)

_ASK_PROMPT = (
    "You are in ASK mode. Analyze the codebase and answer the user's question. "
    "Do not modify files.\n\n"
    "User question:\n"
)

_RESEARCH_PROMPT = (
    "You are in RESEARCH mode. Read the repository context and answer the user's research "
    "question. Do not modify files.\n\n"
    "Use internet search when it is useful or necessary for the question, similar to a deep "
    "research workflow. Compare multiple perspectives or sources when possible, and clearly "
    "separate repository-derived facts from external findings. Include citations or source "
    "links for external claims, call out uncertainty or limitations, and finish with a direct "
    "answer to the user's problem.\n\n"
    "User research request:\n"
)


@dataclass(frozen=True)
class ModeSpec:
    name: str
    read_only: bool
    prompt: str
    slash: bool = True
    aliases: tuple[str, ...] = ()
    help: dict[str, str] = field(default_factory=dict)
    label: dict[str, str] = field(default_factory=dict)
    builtin: bool = False


_BUILTIN_SPECS: tuple[ModeSpec, ...] = (
    ModeSpec(
        name=JobMode.AGENT.value,
        read_only=False,
        prompt="",
        slash=False,
        builtin=True,
    ),
    ModeSpec(
        name=JobMode.PLAN.value,
        read_only=True,
        prompt=_PLAN_PROMPT,
        slash=True,
        aliases=("계획",),
        builtin=True,
    ),
    ModeSpec(
        name=JobMode.ASK.value,
        read_only=True,
        prompt=_ASK_PROMPT,
        slash=True,
        aliases=("질문",),
        builtin=True,
    ),
    ModeSpec(
        name=JobMode.RESEARCH.value,
        read_only=True,
        prompt=_RESEARCH_PROMPT,
        slash=True,
        aliases=("조사",),
        builtin=True,
    ),
    ModeSpec(
        name=JobMode.AGENT_FIX.value,
        read_only=False,
        prompt="",
        slash=False,
        aliases=("fix", "수정"),
        builtin=True,
    ),
)


class ModeRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, ModeSpec] = {spec.name: spec for spec in _BUILTIN_SPECS}
        self._triggers: dict[str, str] = self._build_trigger_index(self._specs.values())

    @staticmethod
    def _build_trigger_index(specs) -> dict[str, str]:
        triggers: dict[str, str] = {}
        for spec in specs:
            keywords = list(spec.aliases)
            if spec.slash:
                keywords.append(spec.name)
            for keyword in keywords:
                triggers[keyword.lower()] = spec.name
        return triggers

    def lookup(self, name: str) -> ModeSpec | None:
        return self._specs.get(name)

    def resolve_trigger(self, keyword: str) -> str | None:
        normalized = keyword.lstrip("/").lower()
        return self._triggers.get(normalized)

    def is_read_only(self, name: str) -> bool:
        spec = self._specs.get(name)
        return spec.read_only if spec is not None else False

    def names(self) -> list[str]:
        return list(self._specs)

    def slash_names(self) -> list[str]:
        return [spec.name for spec in self._specs.values() if spec.slash]


@lru_cache
def get_mode_registry() -> ModeRegistry:
    # Process-wide singleton built once at boot. Later phases load YAML addons into the same
    # instance; consumers (schemas, parser, command registry) read from this shared registry.
    return ModeRegistry()
