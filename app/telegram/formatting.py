"""BotFather-style message formatting via Telegram message entities.

The outbound text stays untouched; formatting is expressed as ``entities``
(bold titles, monospace identifiers) the same way BotFather messages are
rendered. Offsets/lengths follow the Bot API contract (UTF-16 code units).
"""

from __future__ import annotations

import re

from app.telegram.tables import TABLE_CLOSE, TABLE_OPEN

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


def _utf16_units(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def _extract_pre_blocks(text: str) -> tuple[str, list[dict[str, int | str]]]:
    """Strip TABLE sentinel lines from ``text`` and return ``pre`` entity ranges
    over the resulting cleaned text. Mis-matched sentinels are left as-is so the
    surrounding entity logic still runs cleanly.
    """
    if TABLE_OPEN not in text and TABLE_CLOSE not in text:
        return text, []
    lines = text.split("\n")
    cleaned: list[str] = []
    entities: list[dict[str, int | str]] = []
    offset = 0
    block_start: int | None = None
    for line in lines:
        if line == TABLE_OPEN:
            block_start = offset
            continue
        if line == TABLE_CLOSE:
            if block_start is not None:
                length = offset - block_start
                if length > 0:
                    # Drop the trailing newline that joined the last body line to
                    # the close sentinel so the pre block spans only the rows.
                    entities.append(
                        {"type": "pre", "offset": block_start, "length": length - 1}
                    )
                block_start = None
            continue
        cleaned.append(line)
        offset += _utf16_units(line) + 1
    return "\n".join(cleaned), entities


def prepare_outgoing(text: str) -> tuple[str, list[dict[str, int | str]]]:
    """Strip table sentinels and return the final outgoing text plus the full
    entity list (pre blocks first, then bold/code from the cleaned body)."""
    cleaned, pre_entities = _extract_pre_blocks(text)
    return cleaned, pre_entities + build_message_entities(cleaned)


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
                match = _CODE_VALUE_LINE.match(line)
                if match is not None and not match.group("value").startswith("("):
                    entities.append(
                        {
                            "type": "code",
                            "offset": offset + _utf16_units(match.group("prefix")),
                            "length": _utf16_units(match.group("value")),
                        }
                    )
        offset += line_units + 1
    return entities
