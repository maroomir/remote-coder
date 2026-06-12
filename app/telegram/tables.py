"""Monospace table rendering for Telegram `pre` entity blocks.

Outputs are wrapped in sentinel markers that ``app.telegram.formatting`` strips
when it builds message entities, leaving the body inside a single preformatted
block in the final Telegram message.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence

TABLE_OPEN = "​[[TABLE]]​"
TABLE_CLOSE = "​[[/TABLE]]​"

_TRUNCATE_ELLIPSIS = "..."
_LAST_COLUMN_MAX = 30


def display_width(text: str) -> int:
    width = 0
    for ch in text:
        if unicodedata.combining(ch):
            continue
        eaw = unicodedata.east_asian_width(ch)
        width += 2 if eaw in ("W", "F") else 1
    return width


def pad_to_width(text: str, width: int, *, side: str = "left") -> str:
    extra = width - display_width(text)
    if extra <= 0:
        return text
    padding = " " * extra
    return text + padding if side == "left" else padding + text


def _truncate_last_column(value: str, limit: int) -> str:
    if display_width(value) <= limit:
        return value
    target = limit - len(_TRUNCATE_ELLIPSIS)
    if target <= 0:
        return _TRUNCATE_ELLIPSIS[:limit]
    out_chars: list[str] = []
    used = 0
    for ch in value:
        ch_w = 0 if unicodedata.combining(ch) else (2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1)
        if used + ch_w > target:
            break
        out_chars.append(ch)
        used += ch_w
    return "".join(out_chars) + _TRUNCATE_ELLIPSIS


def render_table(
    rows: Sequence[Sequence[str]],
    *,
    headers: Sequence[str] | None = None,
    min_widths: Sequence[int] | None = None,
) -> str:
    """Render a sentinel-wrapped monospace table.

    Columns are left-aligned, separated by two spaces. When ``headers`` is given,
    an ASCII underline row using ``-`` follows the header.
    The last column is truncated with an ellipsis when wider than 30 columns so
    the message body never forces horizontal scrolling on mobile clients.
    """
    if not rows and not headers:
        return f"{TABLE_OPEN}\n{TABLE_CLOSE}"

    normalized_rows: list[list[str]] = []
    column_count = max(
        (len(row) for row in rows),
        default=len(headers) if headers else 0,
    )
    if headers is not None:
        column_count = max(column_count, len(headers))
    for row in rows:
        padded = list(row) + [""] * (column_count - len(row))
        last_index = column_count - 1
        if last_index >= 0:
            padded[last_index] = _truncate_last_column(padded[last_index], _LAST_COLUMN_MAX)
        normalized_rows.append(padded)

    header_row = list(headers) if headers else None
    if header_row is not None:
        header_row.extend([""] * (column_count - len(header_row)))

    widths = [0] * column_count
    if min_widths is not None:
        for idx, mw in enumerate(min_widths[:column_count]):
            widths[idx] = max(widths[idx], mw)
    if header_row is not None:
        for idx, cell in enumerate(header_row):
            widths[idx] = max(widths[idx], display_width(cell))
    for row in normalized_rows:
        for idx, cell in enumerate(row):
            widths[idx] = max(widths[idx], display_width(cell))

    lines: list[str] = [TABLE_OPEN]
    if header_row is not None:
        lines.append(_format_row(header_row, widths))
        lines.append(_format_row(["-" * w for w in widths], widths))
    for row in normalized_rows:
        lines.append(_format_row(row, widths))
    lines.append(TABLE_CLOSE)
    return "\n".join(lines)


def _format_row(cells: Sequence[str], widths: Sequence[int]) -> str:
    padded = [pad_to_width(cell, widths[idx]) for idx, cell in enumerate(cells)]
    return "  ".join(padded).rstrip()
