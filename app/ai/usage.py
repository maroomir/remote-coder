from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Final

_MODEL_VALUE_LIMIT: Final[int] = 80

_MODEL_FIELD_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(
        r"(?im)^\s*(?:actual\s+model|selected\s+model|current\s+model|model|사용\s*모델)\s*[:=]\s*([^\n,;]+)"
    ),
    re.compile(r"(?im)\b(?:using|selected)\s+(?:model\s+)?([A-Za-z][\w .:/-]{1,70}\d(?:\.\d+)?)"),
)
_TOKEN_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(
        r"(?i)\b(input|prompt|output|completion|cached|cache\s+read|cache\s+write|total)\s*"
        r"(?:tokens?|토큰)\s*[:=]\s*([0-9][0-9,._]*)"
    ),
    re.compile(
        r"(?i)\b(input_tokens|prompt_tokens|output_tokens|completion_tokens|cached_tokens|total_tokens)"
        r'["\']?\s*[:=]\s*([0-9][0-9,._]*)'
    ),
    re.compile(
        r"(?i)\b(input|prompt|output|completion|cached|total)\s*[:=]\s*([0-9][0-9,._]*)\s*(?:tokens?|토큰)"
    ),
)


@dataclass(frozen=True)
class RunnerUsage:
    actual_model: str | None = None
    token_usage: dict[str, int] = field(default_factory=dict)

    @property
    def total_tokens(self) -> int | None:
        if "total" in self.token_usage:
            return self.token_usage["total"]
        values = [
            value
            for label, value in self.token_usage.items()
            if label not in {"total", "cache read", "cache write"}
        ]
        if not values:
            return None
        return sum(values)


def extract_runner_usage(text: str) -> RunnerUsage:
    return RunnerUsage(
        actual_model=_extract_actual_model(text),
        token_usage=_extract_token_metrics(text),
    )


def merge_token_usage(target: dict[str, int], source: dict[str, int]) -> None:
    for label, value in source.items():
        target[label] = target.get(label, 0) + value


def format_token_usage(token_usage: dict[str, int]) -> str | None:
    total = RunnerUsage(token_usage=token_usage).total_tokens
    if total is None:
        return None
    details = _format_token_usage_details(token_usage)
    if details:
        return f"{total:,} ({details})"
    return f"{total:,}"


def _format_token_usage_details(token_usage: dict[str, int]) -> str | None:
    labels = ("input", "output", "cached", "total", "cache read", "cache write")
    rendered = [
        f"{label}={token_usage[label]:,}"
        for label in labels
        if label in token_usage
    ]
    rendered.extend(
        f"{label}={value:,}"
        for label, value in sorted(token_usage.items())
        if label not in labels
    )
    return ", ".join(rendered) if rendered else None


def _extract_actual_model(text: str) -> str | None:
    for pattern in _MODEL_FIELD_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        value = _sanitize_metric_value(match.group(1))
        if value:
            return value[:_MODEL_VALUE_LIMIT]
    return None


def _extract_token_metrics(text: str) -> dict[str, int]:
    # Keep the largest value seen per label rather than summing. A single runner
    # output reports cumulative totals, so the same metric appearing twice -- in two
    # syntactic forms, or mirrored on stdout and stderr -- must not be double-counted.
    metrics: dict[str, int] = {}
    for pattern in _TOKEN_PATTERNS:
        for match in pattern.finditer(text):
            label = _normalize_token_label(match.group(1))
            value = _parse_int(match.group(2))
            if value is None:
                continue
            metrics[label] = max(metrics.get(label, 0), value)
    return metrics


def _normalize_token_label(raw: str) -> str:
    key = raw.lower().replace("_", " ").strip()
    if key in {"prompt", "prompt tokens"}:
        return "input"
    if key in {"completion", "completion tokens"}:
        return "output"
    if key in {"input tokens"}:
        return "input"
    if key in {"output tokens"}:
        return "output"
    if key in {"cached tokens"}:
        return "cached"
    if key in {"total tokens"}:
        return "total"
    return key


def _parse_int(raw: str) -> int | None:
    normalized = raw.replace(",", "").replace("_", "").strip()
    if not normalized.isdigit():
        return None
    return int(normalized)


def _sanitize_metric_value(raw: str) -> str:
    return re.sub(r"\s+", " ", raw).strip().strip("`'\"")
