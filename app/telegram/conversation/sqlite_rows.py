from __future__ import annotations

from app.telegram.conversation.models import ConversationEntry


def row_to_entry(row: tuple[object, ...]) -> ConversationEntry:
    return ConversationEntry(
        id=int(row[0]),
        project=str(row[1]),
        chat_id=int(row[2]),
        role=str(row[3]),
        text=str(row[4]),
        job_id=str(row[5]) if row[5] is not None else None,
        message_id=int(row[6]) if len(row) > 6 and row[6] is not None else None,
        reply_to_message_id=int(row[7]) if len(row) > 7 and row[7] is not None else None,
    )


__all__ = ["row_to_entry"]
