from __future__ import annotations

import subprocess
from pathlib import Path


class GitWorktreeService:
    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def _run_git(self, project_path: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=project_path,
            capture_output=True,
            text=True,
            check=False,
            shell=False,
        )

    def prepare_worktree(self, project_path: Path, branch_name: str, job_id: str) -> Path:
        worktree_path = self._base_dir / job_id
        result = self._run_git(project_path, ["worktree", "add", "-b", branch_name, str(worktree_path)])
        if result.returncode != 0:
            raise RuntimeError(f"failed to create worktree: {result.stderr.strip()}")
        return worktree_path

    def collect_changes(self, worktree_path: Path) -> list[str]:
        result = self._run_git(worktree_path, ["status", "--porcelain"])
        if result.returncode != 0:
            raise RuntimeError(f"failed to collect changes: {result.stderr.strip()}")
        files: list[str] = []
        for line in result.stdout.splitlines():
            if len(line) > 3:
                files.append(line[3:].strip())
        return files

    def commit_all(self, worktree_path: Path, message: str) -> str | None:
        add_result = self._run_git(worktree_path, ["add", "."])
        if add_result.returncode != 0:
            raise RuntimeError(f"failed to stage changes: {add_result.stderr.strip()}")
        diff_result = self._run_git(worktree_path, ["diff", "--cached", "--name-only"])
        if diff_result.returncode != 0:
            raise RuntimeError(f"failed to inspect staged files: {diff_result.stderr.strip()}")
        if not diff_result.stdout.strip():
            return None
        commit_result = self._run_git(worktree_path, ["commit", "-m", message])
        if commit_result.returncode != 0:
            raise RuntimeError(f"failed to commit: {commit_result.stderr.strip()}")
        hash_result = self._run_git(worktree_path, ["rev-parse", "--short", "HEAD"])
        if hash_result.returncode != 0:
            raise RuntimeError(f"failed to resolve commit hash: {hash_result.stderr.strip()}")
        return hash_result.stdout.strip()

    def cleanup_worktree(self, project_path: Path, worktree_path: Path) -> None:
        result = self._run_git(project_path, ["worktree", "remove", "--force", str(worktree_path)])
        if result.returncode != 0:
            raise RuntimeError(f"failed to cleanup worktree: {result.stderr.strip()}")
