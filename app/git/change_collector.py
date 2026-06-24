from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from app.monitoring.events import EventLogger

if TYPE_CHECKING:
    import subprocess

_gitlog = EventLogger("app.git.service", "git.operation")

RunGit = Callable[[Path, list[str]], "subprocess.CompletedProcess[str]"]


class ChangeCollector:
    """Collect a worktree's changes and turn them into commits."""

    def __init__(self, run_git: RunGit) -> None:
        self._run_git = run_git

    def collect_diff_numstat(
        self, worktree_path: Path
    ) -> list[tuple[str, int | None, int | None]]:
        """Return per-file (path, added, deleted) line counts for the job's changes against HEAD.

        Uses `git add -N` (intent-to-add) first so brand-new untracked files show up in the diff
        with their real line counts, then diffs the working tree against HEAD. This captures the
        job's edits whether or not they have been committed yet, and must be called before the
        worktree is cleaned up. Binary files report `--` in numstat, which we surface as None so
        callers can label them instead of pretending they had zero line edits.
        """
        intent = self._run_git(worktree_path, ["add", "-N", "."])
        if intent.returncode != 0:
            _gitlog.warning("collect_diff_numstat intent-to-add failed stderr_len=%d", len(intent.stderr))
            raise RuntimeError(f"failed to stage diff stats: {intent.stderr.strip()}")
        result = self._run_git(worktree_path, ["diff", "HEAD", "--numstat", "-z"])
        if result.returncode != 0:
            _gitlog.warning("collect_diff_numstat failed stderr_len=%d", len(result.stderr))
            raise RuntimeError(f"failed to collect diff stats: {result.stderr.strip()}")
        # `-z` NUL-terminates each record. For renames numstat emits the old and new paths as two
        # extra NUL fields after the counts, so we consume those follow-up fields when present.
        stats: list[tuple[str, int | None, int | None]] = []
        fields = [field for field in result.stdout.split("\0") if field]
        index = 0
        while index < len(fields):
            record = fields[index]
            index += 1
            parts = record.split("\t")
            if len(parts) < 3:
                continue
            # Rejoin any trailing fragments so a (legal) tab inside a filename is preserved
            # instead of silently truncating the path at the first tab.
            added_token, deleted_token, path = parts[0], parts[1], "\t".join(parts[2:])
            if not path:
                # Rename/copy: the path is empty in the count record and the real old/new paths
                # follow as the next two NUL fields. Keep the new (destination) path.
                if index + 1 < len(fields):
                    path = fields[index + 1]
                    index += 2
                else:
                    continue
            added = int(added_token) if added_token.isdigit() else None
            deleted = int(deleted_token) if deleted_token.isdigit() else None
            stats.append((path, added, deleted))
        _gitlog.info("collect_diff_numstat count=%d", len(stats))
        return stats

    def collect_changes(self, worktree_path: Path) -> list[str]:
        result = self._run_git(worktree_path, ["status", "--porcelain", "-z"])
        if result.returncode != 0:
            _gitlog.warning("collect_changes failed stderr_len=%d", len(result.stderr))
            raise RuntimeError(f"failed to collect changes: {result.stderr.strip()}")
        # `-z` splits entries on NUL and leaves paths unquoted. A rename or copy emits
        # the destination path right after its status code, followed by a separate NUL
        # field for the origin path, so we keep the destination and skip the origin.
        files: list[str] = []
        entries = result.stdout.split("\0")
        index = 0
        while index < len(entries):
            entry = entries[index]
            index += 1
            if len(entry) <= 3:
                continue
            files.append(entry[3:])
            if entry[0] in ("R", "C"):
                index += 1
        _gitlog.info("collect_changes count=%d", len(files))
        return files

    def commit_all(self, worktree_path: Path, message: str) -> str | None:
        _gitlog.info("commit_all start message_len=%d", len(message))
        add_result = self._run_git(worktree_path, ["add", "."])
        if add_result.returncode != 0:
            _gitlog.warning("commit_all stage failed stderr_len=%d", len(add_result.stderr))
            raise RuntimeError(f"failed to stage changes: {add_result.stderr.strip()}")
        diff_result = self._run_git(worktree_path, ["diff", "--cached", "--name-only"])
        if diff_result.returncode != 0:
            _gitlog.warning("commit_all inspect staged failed stderr_len=%d", len(diff_result.stderr))
            raise RuntimeError(f"failed to inspect staged files: {diff_result.stderr.strip()}")
        if not diff_result.stdout.strip():
            _gitlog.info("commit_all skipped no staged files")
            return None
        staged_count = len([ln for ln in diff_result.stdout.splitlines() if ln.strip()])
        _gitlog.info("commit_all staged_count=%d", staged_count)
        commit_result = self._run_git(worktree_path, ["commit", "-m", message])
        if commit_result.returncode != 0:
            _gitlog.warning("commit_all commit failed stderr_len=%d", len(commit_result.stderr))
            raise RuntimeError(f"failed to commit: {commit_result.stderr.strip()}")
        hash_result = self._run_git(worktree_path, ["rev-parse", "--short", "HEAD"])
        if hash_result.returncode != 0:
            _gitlog.warning("commit_all hash failed stderr_len=%d", len(hash_result.stderr))
            raise RuntimeError(f"failed to resolve commit hash: {hash_result.stderr.strip()}")
        short_hash = hash_result.stdout.strip()
        _gitlog.info("commit_all ok hash=%s", short_hash)
        return short_hash

    def amend_commit(self, worktree_path: Path, message: str) -> str:
        _gitlog.info("amend_commit start message_len=%d", len(message))
        add_result = self._run_git(worktree_path, ["add", "."])
        if add_result.returncode != 0:
            _gitlog.warning("amend_commit stage failed stderr_len=%d", len(add_result.stderr))
            raise RuntimeError(f"failed to stage changes: {add_result.stderr.strip()}")
        commit_result = self._run_git(
            worktree_path,
            ["commit", "--amend", "--allow-empty", "-m", message],
        )
        if commit_result.returncode != 0:
            _gitlog.warning("amend_commit failed stderr_len=%d", len(commit_result.stderr))
            raise RuntimeError(f"failed to amend commit: {commit_result.stderr.strip()}")
        hash_result = self._run_git(worktree_path, ["rev-parse", "--short", "HEAD"])
        if hash_result.returncode != 0:
            _gitlog.warning("amend_commit hash failed stderr_len=%d", len(hash_result.stderr))
            raise RuntimeError(f"failed to resolve commit hash: {hash_result.stderr.strip()}")
        short_hash = hash_result.stdout.strip()
        _gitlog.info("amend_commit ok hash=%s", short_hash)
        return short_hash
