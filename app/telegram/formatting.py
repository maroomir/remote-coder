"""BotFather-style message formatting via Telegram message entities.

The outbound text stays untouched; formatting is expressed as ``entities``
(bold titles, monospace identifiers) the same way BotFather messages are
rendered. Offsets/lengths follow the Bot API contract (UTF-16 code units).
"""

from __future__ import annotations

import re

_SECTION_HEADINGS = frozenset(
    {
        "Options",
        "옵션",
        "⚙️ Options",
        "⚙️ 옵션",
        "Commands:",
        "명령어 목록:",
        "📋 Commands",
        "📋 명령어 목록",
        "Rows by role",
        "역할별 행 수",
        "Local branches",
        "로컬 브랜치",
        "Remote branches",
        "원격 브랜치",
        "Worktree entries",
        "Worktree 항목",
        "Usage",
        "사용법",
        "Examples",
        "예시",
        "💡 Examples",
        "💡 예시",
        "Prerequisites",
        "전제조건",
        "AI response:",
        "AI 응답:",
        "Failure output summary:",
        "실패 출력 요약:",
        "Current output:",
        "현재 출력:",
    }
)

# Once one of these lines appears, the rest of the message is free-form body
# (AI output, logs); stop adding entities so the body renders verbatim.
_BODY_MARKERS = frozenset(
    {
        "AI response:",
        "AI 응답:",
        "Failure output summary:",
        "실패 출력 요약:",
        "Current output:",
        "현재 출력:",
    }
)

_CODE_VALUE_LINE = re.compile(
    r"^(?P<prefix>\s*-\s*(?:Job ID|Session ID|Branch|Commit|Log path|브랜치|커밋|로그 경로)\s*:\s*)(?P<value>\S.*?)\s*$"
)
_COMMAND_LIST_LINE = re.compile(r"^\s*-\s+(?P<command>/\S+(?:\s+\S.*)?)\s*$")


def _utf16_units(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def prepare_outgoing(text: str) -> tuple[str, list[dict[str, int | str]]]:
    return text, build_message_entities(text)


def build_message_entities(text: str) -> list[dict[str, int | str]]:
    """Compute BotFather-like entities (bold title/headings, code values)."""
    lines = text.split("\n")
    non_empty = sum(1 for line in lines if line.strip())
    entities: list[dict[str, int | str]] = []
    offset = 0
    title_done = non_empty < 2
    body_started = False
    for line in lines:
        line_units = _utf16_units(line)
        stripped = line.strip()
        if stripped and not body_started:
            lead_units = _utf16_units(line[: len(line) - len(line.lstrip())])
            if not title_done:
                entities.append(
                    {"type": "bold", "offset": offset + lead_units, "length": _utf16_units(stripped)}
                )
                title_done = True
            elif stripped in _SECTION_HEADINGS:
                entities.append(
                    {"type": "bold", "offset": offset + lead_units, "length": _utf16_units(stripped)}
                )
                if stripped in _BODY_MARKERS:
                    body_started = True
            else:
                command_match = _COMMAND_LIST_LINE.match(line)
                if command_match is not None:
                    command = command_match.group("command")
                    entities.append(
                        {
                            "type": "code",
                            "offset": offset + _utf16_units(line[: command_match.start("command")]),
                            "length": _utf16_units(command),
                        }
                    )
                else:
                    value_match = _CODE_VALUE_LINE.match(line)
                    if value_match is not None and not value_match.group("value").startswith("("):
                        entities.append(
                            {
                                "type": "code",
                                "offset": offset + _utf16_units(value_match.group("prefix")),
                                "length": _utf16_units(value_match.group("value")),
                            }
                        )
        offset += line_units + 1
    return entities
