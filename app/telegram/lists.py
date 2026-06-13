from __future__ import annotations

from collections.abc import Sequence


def render_labeled_list(rows: Sequence[tuple[str, str]]) -> str:
    lines: list[str] = []
    for label, value in rows:
        value_lines = str(value).splitlines() or [""]
        lines.append(f"- {label}: {value_lines[0]}")
        lines.extend(f"  {line}" for line in value_lines[1:])
    return "\n".join(lines)


def render_command_list(rows: Sequence[tuple[str, str, str]]) -> str:
    lines: list[str] = []
    for command, args, description in rows:
        signature = " ".join(part for part in (command, args) if part)
        lines.extend((f"- {signature}", f"  {description}"))
    return "\n".join(lines)
