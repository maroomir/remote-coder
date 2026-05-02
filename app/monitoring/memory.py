"""SQLite 대화 기억 모니터링 포맷."""

from __future__ import annotations

from app.telegram.conversation import ConversationDbChatStats


def format_memory_monitor(stats: ConversationDbChatStats, project: str, chat_id: int) -> str:
    size_kb = stats.db_size_bytes / 1024.0 if stats.db_size_bytes else 0.0
    roles = ", ".join(f"{k}={v}" for k, v in sorted(stats.rows_by_role.items()))
    lines = [
        "메모리(SQLite)",
        f"프로젝트: {project}",
        f"chat_id: {chat_id}",
        f"DB 경로: {stats.db_path}",
        f"DB 존재: {'예' if stats.db_exists else '아니오'}",
        f"DB 크기: {size_kb:.2f} KiB ({stats.db_size_bytes} bytes)",
        f"이 채팅 저장 행 수: {stats.total_rows}",
        f"역할별 행 수: {roles or '(없음)'}",
    ]
    return "\n".join(lines)
