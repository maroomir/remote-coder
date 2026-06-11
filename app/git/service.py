from __future__ import annotations

import subprocess
import uuid
from pathlib import Path

import app.git.worktree_service as _impl
from app.git.worktree_service import GitWorktreeService as _GitWorktreeService


class GitWorktreeService(_GitWorktreeService):
    def _run_git(self, cwd: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            shell=False,
        )

    def _run_gh(
        self, project_path: Path, args: list[str]
    ) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                args,
                cwd=project_path,
                capture_output=True,
                text=True,
                check=False,
                shell=False,
                timeout=self._GH_TIMEOUT_SECONDS,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                "GitHub CLI (`gh`) is not installed or not available on PATH."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"GitHub CLI command timed out after {self._GH_TIMEOUT_SECONDS} seconds."
            ) from exc
        except OSError as exc:
            raise RuntimeError(f"GitHub CLI could not be executed: {exc}") from exc

    def rebase_branch_onto_main_and_merge(
        self,
        project_path: Path,
        branch: str,
        remote: str,
        worktree_ops_base: Path,
    ) -> str:
        old_uuid = _impl.uuid
        _impl.uuid = uuid
        try:
            return super().rebase_branch_onto_main_and_merge(
                project_path, branch, remote, worktree_ops_base
            )
        finally:
            _impl.uuid = old_uuid

__all__ = ["GitWorktreeService"]
