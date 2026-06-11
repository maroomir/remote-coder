from __future__ import annotations

from typing import Any

__all__ = [
    "format_branch_monitor",
    "format_memory_monitor",
    "format_model_monitor",
    "format_worktree_monitor",
]


def __getattr__(name: str) -> Any:
    if name in {"format_branch_monitor", "format_worktree_monitor"}:
        from app.monitoring import git

        return getattr(git, name)
    if name == "format_memory_monitor":
        from app.monitoring.memory import format_memory_monitor

        return format_memory_monitor
    if name == "format_model_monitor":
        from app.monitoring.model import format_model_monitor

        return format_model_monitor
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
