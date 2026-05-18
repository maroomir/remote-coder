from __future__ import annotations

from app.telegram.conversation import ConversationDbChatStats


def format_memory_monitor(stats: ConversationDbChatStats, project: str, chat_id: int) -> str:
    size_kb = stats.db_size_bytes / 1024.0 if stats.db_size_bytes else 0.0
    roles = ", ".join(f"{k}={v}" for k, v in sorted(stats.rows_by_role.items()))
    lines = [
        "Memory (SQLite)",
        f"Project: {project}",
        f"chat_id: {chat_id}",
        f"DB path: {stats.db_path}",
        f"DB exists: {'yes' if stats.db_exists else 'no'}",
        f"DB size: {size_kb:.2f} KiB ({stats.db_size_bytes} bytes)",
        f"Rows for this chat: {stats.total_rows}",
        f"Rows by role: {roles or '(none)'}",
    ]
    return "\n".join(lines)
