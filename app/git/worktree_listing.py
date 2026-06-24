from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from app.monitoring.events import EventLogger

if TYPE_CHECKING:
    import subprocess

_gitlog = EventLogger("app.git.service", "git.operation")

RunGit = Callable[[Path, list[str]], "subprocess.CompletedProcess[str]"]
ParseWorktreeList = Callable[[str], list[tuple[Path, str | None]]]


class WorktreeListing:
    """Inspect the `git worktree list` porcelain output for branch lookups."""

    def __init__(self, run_git: RunGit, parse_worktree_list: ParseWorktreeList) -> None:
        self._run_git = run_git
        self._parse_worktree_list_porcelain = parse_worktree_list

    def find_linked_worktree_for_branch(
        self, project_path: Path, branch_name: str
    ) -> Path | None:
        _gitlog.info("find_linked_worktree_for_branch start branch=%s", branch_name)
        result = self._run_git(project_path, ["worktree", "list", "--porcelain"])
        if result.returncode != 0:
            _gitlog.warning(
                "find_linked_worktree_for_branch failed branch=%s stderr_len=%d",
                branch_name,
                len(result.stderr),
            )
            raise RuntimeError(f"failed to list worktrees: {result.stderr.strip()}")
        root = project_path.resolve()
        for worktree_path, branch in self._parse_worktree_list_porcelain(result.stdout):
            if branch != branch_name:
                continue
            if worktree_path.resolve() == root:
                continue
            _gitlog.info("find_linked_worktree_for_branch hit branch=%s", branch_name)
            return worktree_path
        _gitlog.info("find_linked_worktree_for_branch miss branch=%s", branch_name)
        return None

    def branch_is_checked_out(self, project_path: Path, branch_name: str) -> bool:
        _gitlog.info("branch_is_checked_out start branch=%s", branch_name)
        result = self._run_git(project_path, ["worktree", "list", "--porcelain"])
        if result.returncode != 0:
            _gitlog.warning(
                "branch_is_checked_out failed branch=%s stderr_len=%d",
                branch_name,
                len(result.stderr),
            )
            raise RuntimeError(f"failed to list worktrees: {result.stderr.strip()}")
        checked_out = any(
            branch == branch_name
            for _, branch in self._parse_worktree_list_porcelain(result.stdout)
        )
        _gitlog.info("branch_is_checked_out branch=%s checked_out=%s", branch_name, checked_out)
        return checked_out

    def list_worktree_entries(self, project_path: Path) -> list[tuple[Path, str | None]]:
        result = self._run_git(project_path, ["worktree", "list", "--porcelain"])
        if result.returncode != 0:
            raise RuntimeError(f"failed to list worktrees: {result.stderr.strip()}")
        return self._parse_worktree_list_porcelain(result.stdout)
