from __future__ import annotations

from threading import Lock

# Shared in-flight guard for destructive single-branch git operations (rebase, cherry-pick to
# main, discard). Keyed by (repo_root, remote, branch) so that rebasing, cherry-picking, or
# discarding the *same* branch cannot run concurrently and corrupt each other's worktrees, while
# operations on different branches stay independent.

_guard = Lock()
_inflight_keys: set[tuple[str, str, str]] = set()

BranchOpKey = tuple[str, str, str]


def acquire_branch_op(key: BranchOpKey) -> bool:
    """Reserve the key. Returns False if an operation on the same branch is already running."""
    with _guard:
        if key in _inflight_keys:
            return False
        _inflight_keys.add(key)
        return True


def release_branch_op(key: BranchOpKey) -> None:
    with _guard:
        _inflight_keys.discard(key)
