from __future__ import annotations

from app.telegram.conversation import ConversationDbChatStats
from app.telegram.tables import render_table


def format_memory_monitor(stats: ConversationDbChatStats, project: str, chat_id: int) -> str:
    size_kb = stats.db_size_bytes / 1024.0 if stats.db_size_bytes else 0.0
    rows: list[tuple[str, str]] = [
        ("Project", project),
        ("chat_id", str(chat_id)),
        ("DB path", str(stats.db_path)),
        ("DB exists", "yes" if stats.db_exists else "no"),
        ("DB size", f"{size_kb:.2f} KiB ({stats.db_size_bytes} bytes)"),
        ("Rows for this chat", str(stats.total_rows)),
        ("Sessions", str(stats.session_count)),
    ]
    if stats.rows_by_role:
        for role, count in sorted(stats.rows_by_role.items()):
            rows.append((f"  role:{role}", str(count)))
    else:
        rows.append(("Rows by role", "(none)"))
    return "Memory (SQLite)\n" + render_table(rows, headers=("metric", "value"))
