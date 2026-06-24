from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from app.monitoring.events import EventLogger

if TYPE_CHECKING:
    import subprocess

_gitlog = EventLogger("app.git.service", "git.operation")

RunGit = Callable[[Path, list[str]], "subprocess.CompletedProcess[str]"]


class BranchQuery:
    """Read-only branch lookups and listing/formatting over a project's refs."""

    def __init__(self, run_git: RunGit) -> None:
        self._run_git = run_git

    def resolve_integrate_branch(self, project_path: Path) -> str:
        for candidate in ("main", "master"):
            result = self._run_git(project_path, ["rev-parse", "--verify", candidate])
            if result.returncode == 0:
                return candidate
        raise RuntimeError(
            "No integration branch (main or master). The repository needs main or master."
        )

    def get_current_branch(self, project_path: Path) -> str:
        """Return the checked-out local branch name, or a detached HEAD label."""
        result = self._run_git(project_path, ["branch", "--show-current"])
        if result.returncode != 0:
            raise RuntimeError(f"failed to read current branch: {result.stderr.strip()}")
        name = result.stdout.strip()
        if name:
            return name
        return "(detached HEAD - no branch name)"

    def local_branch_exists(self, project_path: Path, branch: str) -> bool:
        result = self._run_git(project_path, ["show-ref", "--verify", f"refs/heads/{branch}"])
        _gitlog.info("local_branch_exists branch=%s exists=%s", branch, result.returncode == 0)
        return result.returncode == 0

    def format_local_branches(self, project_path: Path) -> str:
        result = self._run_git(project_path, ["branch", "--sort=refname"])
        if result.returncode != 0:
            raise RuntimeError(f"failed to list local branches: {result.stderr.strip()}")
        text = result.stdout.strip()
        return text if text else "(no local branches)"

    def list_local_branches(self, project_path: Path) -> list[str]:
        result = self._run_git(project_path, ["branch", "--sort=refname"])
        if result.returncode != 0:
            raise RuntimeError(f"failed to list local branches: {result.stderr.strip()}")
        branches: list[str] = []
        for line in result.stdout.splitlines():
            name = self._branch_name_from_git_branch_output_line(line)
            if name:
                branches.append(name)
        return sorted(set(branches))

    def list_local_branches_matching(self, project_path: Path, prefix: str) -> list[str]:
        result = self._run_git(project_path, ["branch", "--list", f"{prefix}*"])
        if result.returncode != 0:
            raise RuntimeError(f"failed to list branches: {result.stderr.strip()}")
        branches: list[str] = []
        for line in result.stdout.splitlines():
            name = self._branch_name_from_git_branch_output_line(line)
            if not name:
                continue
            if name.startswith(prefix):
                branches.append(name)
        return sorted(set(branches))

    def count_local_branches(self, project_path: Path) -> int:
        result = self._run_git(project_path, ["branch", "--format=%(refname:short)"])
        if result.returncode != 0:
            raise RuntimeError(f"failed to count local branches: {result.stderr.strip()}")
        return len([ln for ln in result.stdout.splitlines() if ln.strip()])

    def format_remote_branches_for_remote(self, project_path: Path, remote: str) -> str:
        result = self._run_git(project_path, ["branch", "-r", "--sort=refname"])
        if result.returncode != 0:
            raise RuntimeError(f"failed to list remote branches: {result.stderr.strip()}")
        prefix = f"{remote}/"
        lines: list[str] = []
        for raw in result.stdout.splitlines():
            line = raw.strip()
            if not line or "->" in line:
                continue
            if line.startswith(prefix):
                rest = line[len(prefix) :]
                if rest == "HEAD":
                    continue
                lines.append(line)
        return "\n".join(lines) if lines else f"(no remote branches on {remote})"

    def count_remote_branches_for_remote(self, project_path: Path, remote: str) -> int:
        result = self._run_git(project_path, ["branch", "-r", "--sort=refname"])
        if result.returncode != 0:
            raise RuntimeError(f"failed to count remote branches: {result.stderr.strip()}")
        prefix = f"{remote}/"
        n = 0
        for raw in result.stdout.splitlines():
            line = raw.strip()
            if not line or "->" in line:
                continue
            if line.startswith(prefix):
                rest = line[len(prefix) :]
                if rest == "HEAD":
                    continue
                n += 1
        return n

    def list_remote_branches_matching(
        self, project_path: Path, remote: str, prefix: str
    ) -> list[str]:
        result = self._run_git(project_path, ["ls-remote", "--heads", remote])
        if result.returncode != 0:
            raise RuntimeError(f"failed to list remote branches: {result.stderr.strip()}")
        heads_prefix = "refs/heads/"
        branches: list[str] = []
        for raw in result.stdout.splitlines():
            line = raw.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            ref = parts[1]
            if not ref.startswith(heads_prefix):
                continue
            short = ref[len(heads_prefix) :]
            if short == "HEAD" or not short.startswith(prefix):
                continue
            branches.append(short)
        return sorted(set(branches))

    @staticmethod
    def _branch_name_from_git_branch_output_line(line: str) -> str:
        name = line.strip()
        while name and name[0] in "+*":
            name = name[1:].lstrip()
        return name
