from __future__ import annotations

import re

from app.admin.advanced_settings import CONVERSATION_REPLY_SNIPPET_MAX_CHARS_DEFAULT
from app.models import UiLanguage
from app.telegram.conversation.models import ConversationEntry
from app.telegram.i18n import instruction_frame_labels


_AMBIGUOUS_FOLLOWUP = re.compile(
    r"^\s*(작업\s*시작해줘|진행해줘|그거\s*해줘|시작해줘)\s*$",
    re.UNICODE | re.IGNORECASE,
)


def is_ambiguous_followup(text: str) -> bool:
    return bool(_AMBIGUOUS_FOLLOWUP.match(text.strip()))


def truncate_snippet(
    text: str, limit: int = CONVERSATION_REPLY_SNIPPET_MAX_CHARS_DEFAULT
) -> str:
    snippet = text.strip().replace("\r\n", "\n").replace("\r", "\n")
    if len(snippet) > limit:
        return snippet[:limit].rstrip() + "...(truncated)"
    return snippet


class ConversationContextBuilder:
    @staticmethod
    def build(
        entries: list[ConversationEntry],
        current_user_line: str,
        language: UiLanguage = UiLanguage.ENGLISH,
        snippet_max_chars: int = CONVERSATION_REPLY_SNIPPET_MAX_CHARS_DEFAULT,
    ) -> str:
        labels = instruction_frame_labels(language)
        lines: list[str] = [
            labels.prev_context_open,
        ]
        for e in entries:
            label = e.role
            if e.job_id:
                label = f"{e.role} (job_id={e.job_id})"
            snippet = truncate_snippet(e.text, snippet_max_chars)
            lines.append(f"{label}: {snippet}")
        lines.extend(
            [
                labels.prev_context_close,
                "",
                labels.current_request_open,
                current_user_line.strip(),
                labels.current_request_close,
            ]
        )
        return "\n".join(lines)


__all__ = [
    "ConversationContextBuilder",
    "is_ambiguous_followup",
    "truncate_snippet",
]
