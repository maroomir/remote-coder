from __future__ import annotations

import re
import subprocess
import uuid
from collections.abc import Callable
from pathlib import Path

from app.git.branch_query import BranchQuery
from app.git.change_collector import ChangeCollector
from app.git.remote_ops import RemoteOps
from app.git.worktree_lifecycle import WorktreeLifecycle
from app.git.worktree_listing import WorktreeListing
from app.monitoring.events import EventLogger

_SAFE_BRANCH_TOKEN = re.compile(r"^[A-Za-z0-9/._-]+$")

_gitlog = EventLogger("app.git.service", "git.operation")


class GitWorktreeService:
    _GH_TIMEOUT_SECONDS = 30

    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._branch_query = BranchQuery(self._run_git)
        self._worktree_listing = WorktreeListing(
            self._run_git, self._parse_worktree_list_porcelain
        )
        self._change_collector = ChangeCollector(self._run_git)
        self._worktree_lifecycle = WorktreeLifecycle(
            self._base_dir,
            self._run_git,
            self._parse_worktree_list_porcelain,
            self._is_within,
        )
        self._remote_ops = RemoteOps(
            self._run_git,
            self._run_git_checked,
            self._run_gh,
            self._remote_branch_ref,
            self._new_rebase_operation_id,
            self._branch_query,
            self._worktree_listing,
            self._worktree_lifecycle,
        )

    def _run_git(self, cwd: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            shell=False,
        )

    def _run_git_checked(
        self, cwd: Path, args: list[str], error_prefix: str
    ) -> subprocess.CompletedProcess[str]:
        result = self._run_git(cwd, args)
        if result.returncode != 0:
            raise RuntimeError(f"{error_prefix}: {result.stderr.strip()}")
        return result

    @staticmethod
    def _remote_branch_ref(remote: str, branch: str) -> str:
        return f"{remote}/{branch}"

    def resolve_integrate_branch(self, project_path: Path) -> str:
        return self._branch_query.resolve_integrate_branch(project_path)

    def _add_worktree(
        self,
        project_path: Path,
        job_id: str,
        build_args: Callable[[Path], list[str]],
        *,
        log_label: str,
        log_detail: str,
        error_label: str,
        worktree_base_dir: Path | None,
    ) -> Path:
        return self._worktree_lifecycle._add_worktree(
            project_path,
            job_id,
            build_args,
            log_label=log_label,
            log_detail=log_detail,
            error_label=error_label,
            worktree_base_dir=worktree_base_dir,
        )

    def prepare_worktree(
        self,
        project_path: Path,
        branch_name: str,
        job_id: str,
        worktree_base_dir: Path | None = None,
    ) -> Path:
        return self._worktree_lifecycle.prepare_worktree(
            project_path, branch_name, job_id, worktree_base_dir
        )

    def prepare_detached_worktree(
        self,
        project_path: Path,
        job_id: str,
        worktree_base_dir: Path | None = None,
        base_branch: str | None = None,
    ) -> Path:
        return self._worktree_lifecycle.prepare_detached_worktree(
            project_path, job_id, worktree_base_dir, base_branch
        )

    def prepare_branch_worktree(
        self,
        project_path: Path,
        branch_name: str,
        job_id: str,
        worktree_base_dir: Path | None = None,
    ) -> Path:
        return self._worktree_lifecycle.prepare_branch_worktree(
            project_path, branch_name, job_id, worktree_base_dir
        )

    @staticmethod
    def ensure_worktree_writable(worktree_path: Path) -> None:
        probe = worktree_path / ".remote_coder_write_probe"
        try:
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
        except OSError as exc:
            raise RuntimeError(f"worktree is not writable: {worktree_path} ({exc})") from exc

    @staticmethod
    def validate_branch_token(name: str) -> str | None:
        if not name or len(name) > 255:
            return "Branch name is empty or too long."
        if ".." in name or name.startswith("-"):
            return "Branch name is not allowed."
        if not _SAFE_BRANCH_TOKEN.match(name):
            return "Branch names may only use letters, numbers, /, ., _, and -."
        return None

    def get_current_branch(self, project_path: Path) -> str:
        """Return the checked-out local branch name, or a detached HEAD label."""
        return self._branch_query.get_current_branch(project_path)

    def local_branch_exists(self, project_path: Path, branch: str) -> bool:
        return self._branch_query.local_branch_exists(project_path, branch)

    def switch_branch(self, project_path: Path, branch: str) -> None:
        self._remote_ops.switch_branch(project_path, branch)

    def create_branch_in_worktree(self, worktree_path: Path, branch_name: str) -> None:
        self._remote_ops.create_branch_in_worktree(worktree_path, branch_name)

    def find_linked_worktree_for_branch(self, project_path: Path, branch_name: str) -> Path | None:
        return self._worktree_listing.find_linked_worktree_for_branch(project_path, branch_name)

    def branch_is_checked_out(self, project_path: Path, branch_name: str) -> bool:
        return self._worktree_listing.branch_is_checked_out(project_path, branch_name)

    def collect_diff_numstat(self, worktree_path: Path) -> list[tuple[str, int | None, int | None]]:
        return self._change_collector.collect_diff_numstat(worktree_path)

    def collect_changes(self, worktree_path: Path) -> list[str]:
        return self._change_collector.collect_changes(worktree_path)

    def commit_all(self, worktree_path: Path, message: str) -> str | None:
        return self._change_collector.commit_all(worktree_path, message)

    def push_branch(self, project_path: Path, remote: str, branch: str) -> None:
        self._remote_ops.push_branch(project_path, remote, branch)

    def amend_commit(self, worktree_path: Path, message: str) -> str:
        return self._change_collector.amend_commit(worktree_path, message)

    def push_branch_force_with_lease(self, project_path: Path, remote: str, branch: str) -> None:
        self._remote_ops.push_branch_force_with_lease(project_path, remote, branch)

    def cleanup_worktree(self, project_path: Path, worktree_path: Path) -> None:
        self._worktree_lifecycle.cleanup_worktree(project_path, worktree_path)

    def checkout_integrate_branch(self, project_path: Path) -> str:
        return self._remote_ops.checkout_integrate_branch(project_path)

    def format_local_branches(self, project_path: Path) -> str:
        return self._branch_query.format_local_branches(project_path)

    def list_local_branches(self, project_path: Path) -> list[str]:
        return self._branch_query.list_local_branches(project_path)

    def format_remote_branches_for_remote(self, project_path: Path, remote: str) -> str:
        return self._branch_query.format_remote_branches_for_remote(project_path, remote)

    def count_local_branches(self, project_path: Path) -> int:
        return self._branch_query.count_local_branches(project_path)

    def count_remote_branches_for_remote(self, project_path: Path, remote: str) -> int:
        return self._branch_query.count_remote_branches_for_remote(project_path, remote)

    def list_worktree_entries(self, project_path: Path) -> list[tuple[Path, str | None]]:
        return self._worktree_listing.list_worktree_entries(project_path)

    _branch_name_from_git_branch_output_line = staticmethod(
        BranchQuery._branch_name_from_git_branch_output_line
    )

    def list_local_branches_matching(self, project_path: Path, prefix: str) -> list[str]:
        return self._branch_query.list_local_branches_matching(project_path, prefix)

    @staticmethod
    def _parse_worktree_list_porcelain(stdout: str) -> list[tuple[Path, str | None]]:
        entries: list[tuple[Path, str | None]] = []
        cur_path: Path | None = None
        cur_branch: str | None = None
        for line in stdout.splitlines():
            if line.startswith("worktree "):
                if cur_path is not None:
                    entries.append((cur_path, cur_branch))
                cur_path = Path(line[len("worktree ") :].strip())
                cur_branch = None
            elif line.startswith("branch "):
                ref = line[len("branch ") :].strip()
                if ref.startswith("refs/heads/"):
                    cur_branch = ref[len("refs/heads/") :]
                else:
                    cur_branch = None
        if cur_path is not None:
            entries.append((cur_path, cur_branch))
        return entries

    def remove_linked_worktrees_for_branches(self, project_path: Path, branch_names: list[str]) -> None:
        self._worktree_lifecycle.remove_linked_worktrees_for_branches(project_path, branch_names)

    @staticmethod
    def _is_within(path: Path, base: Path) -> bool:
        try:
            path.relative_to(base)
        except ValueError:
            return False
        return True

    def cleanup_managed_worktrees(
        self,
        project_path: Path,
        worktree_base_dir: Path,
        branch_prefix: str = "remote-",
    ) -> int:
        return self._worktree_lifecycle.cleanup_managed_worktrees(
            project_path, worktree_base_dir, branch_prefix
        )

    def list_remote_branches_matching(self, project_path: Path, remote: str, prefix: str) -> list[str]:
        return self._branch_query.list_remote_branches_matching(project_path, remote, prefix)

    def delete_local_branches(self, project_path: Path, branches: list[str]) -> None:
        self._remote_ops.delete_local_branches(project_path, branches)

    def delete_remote_branches(self, project_path: Path, remote: str, branches: list[str]) -> None:
        self._remote_ops.delete_remote_branches(project_path, remote, branches)

    def pull_repository(self, project_path: Path, remote: str) -> str:
        return self._remote_ops.pull_repository(project_path, remote)

    def _new_rebase_operation_id(self) -> str:
        return f"_rebase_{uuid.uuid4().hex[:8]}"

    def rebase_branch_onto_main_and_merge(
        self,
        project_path: Path,
        branch: str,
        remote: str,
        worktree_ops_base: Path,
    ) -> str:
        return self._remote_ops.rebase_branch_onto_main_and_merge(
            project_path, branch, remote, worktree_ops_base
        )

    def cherry_pick_branch_onto_main(
        self,
        project_path: Path,
        branch: str,
        remote: str,
        worktree_ops_base: Path,
    ) -> str:
        return self._remote_ops.cherry_pick_branch_onto_main(
            project_path, branch, remote, worktree_ops_base
        )

    def create_github_pr(
        self,
        project_path: Path,
        branch: str,
        base_branch: str,
        title: str,
        body: str,
    ) -> str:
        return self._remote_ops.create_github_pr(
            project_path, branch, base_branch, title, body
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
