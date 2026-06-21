from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from app.jobs.schemas import JobMode
from app.monitoring.events import EventLogger

_log = EventLogger("app.jobs.mode_registry", "jobs.mode_addon")

# Addon mode names must be lowercase tokens so they never collide with slash syntax or shell-y
# characters; the upper bound also caps trigger-index keys to a sane size.
_ADDON_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,30}$")

_BUILTIN_NAMES = frozenset(mode.value for mode in JobMode)

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

    def register_addon(self, spec: ModeSpec) -> None:
        # Self-guard the core invariant in the method that promises it: addon modes are read-only
        # only, regardless of how the spec was built. Keeps a future caller from injecting a
        # writable addon even if it bypasses _build_addon_spec.
        if spec.read_only is not True:
            raise ValueError(f"addon mode must be read-only: {spec.name}", "writable_denied")
        if spec.name in self._specs:
            raise ValueError(f"mode name already registered: {spec.name}", "duplicate")

        candidate = dict(self._specs)
        candidate[spec.name] = spec
        # Build the trigger index over the merged set first so a slash-name/alias that shadows an
        # existing trigger is rejected before we mutate any state. Silent overwrites would let an
        # addon hijack a builtin keyword like /plan.
        new_triggers = self._build_trigger_index_strict(candidate.values())

        self._specs = candidate
        self._triggers = new_triggers

    @staticmethod
    def _build_trigger_index_strict(specs) -> dict[str, str]:
        triggers: dict[str, str] = {}
        for spec in specs:
            keywords = list(spec.aliases)
            if spec.slash:
                keywords.append(spec.name)
            for keyword in keywords:
                normalized = keyword.lower()
                if normalized in triggers and triggers[normalized] != spec.name:
                    raise ValueError(f"trigger conflict: {normalized}", "trigger_conflict")
                triggers[normalized] = spec.name
        return triggers


def _build_addon_spec(data: object) -> ModeSpec:
    if not isinstance(data, dict):
        raise ValueError("invalid_root")

    name = data.get("name")
    if not isinstance(name, str) or not _ADDON_NAME_PATTERN.match(name):
        raise ValueError("invalid_name")
    if name in _BUILTIN_NAMES:
        raise ValueError("builtin_conflict")

    read_only = data.get("read_only")
    if not isinstance(read_only, bool):
        raise ValueError("missing_field")
    # Core security invariant: user-supplied addon modes are read-only only. Write/commit/push
    # capable modes stay builtin-exclusive so a dropped-in YAML can never grant write access.
    if read_only is not True:
        raise ValueError("writable_denied")

    prompt = data.get("prompt")
    if not isinstance(prompt, str):
        raise ValueError("missing_field")

    slash = data.get("slash", True)
    if not isinstance(slash, bool):
        raise ValueError("invalid_slash")

    aliases = () if "aliases" not in data else _coerce_str_tuple(data["aliases"])
    help_map = {} if "help" not in data else _coerce_lang_map(data["help"])
    if help_map and "en" not in help_map:
        raise ValueError("help_missing_en")
    label_map = {} if "label" not in data else _coerce_lang_map(data["label"])

    return ModeSpec(
        name=name,
        read_only=True,
        prompt=prompt,
        slash=slash,
        aliases=aliases,
        help=help_map,
        label=label_map,
        builtin=False,
    )


def _coerce_str_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError("invalid_aliases")
    if not all(isinstance(item, str) for item in value):
        raise ValueError("invalid_aliases")
    return tuple(value)


def _coerce_lang_map(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError("invalid_lang_map")
    if not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
        raise ValueError("invalid_lang_map")
    return dict(value)


def load_addon_modes(registry: ModeRegistry, directory: Path) -> None:
    # Boot-time, one-shot load of declarative addon modes. Each *.yaml file maps to exactly one
    # read-only mode. Failures are isolated per file: a broken or malicious file is skipped with a
    # short reason token (never a path/token in the message body) so it cannot block startup.
    if not directory.is_dir():
        return

    for path in sorted(directory.glob("*.yaml")):
        try:
            raw = path.read_text(encoding="utf-8")
            data = yaml.safe_load(raw)
            spec = _build_addon_spec(data)
            registry.register_addon(spec)
        except yaml.YAMLError:
            _log.warning("addon mode skipped reason=%s", "parse_error")
        except ValueError as error:
            _log.warning("addon mode skipped reason=%s", _reason_token(error))
        except OSError:
            _log.warning("addon mode skipped reason=%s", "read_error")


def _reason_token(error: ValueError) -> str:
    # register_addon raises (message, token); _build_addon_spec raises just the token. Logging
    # only the short token keeps file paths and YAML field values out of the message body.
    args = error.args
    if len(args) >= 2 and isinstance(args[1], str):
        return args[1]
    return str(args[0]) if args else "rejected"


@lru_cache
def get_mode_registry() -> ModeRegistry:
    # Process-wide singleton built once at boot. Later phases load YAML addons into the same
    # instance; consumers (schemas, parser, command registry) read from this shared registry.
    return ModeRegistry()
