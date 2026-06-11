"""Compatibility facade for the public Git worktree service import path.

The implementation lives in app.git.worktree_service. This module preserves the
historical app.git.service.GitWorktreeService path and its monkeypatch points.
"""

from __future__ import annotations

import subprocess
import uuid
from pathlib import Path

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

    def _new_rebase_operation_id(self) -> str:
        return f"_rebase_{uuid.uuid4().hex[:8]}"


__all__ = ["GitWorktreeService"]
