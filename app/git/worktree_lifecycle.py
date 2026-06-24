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
IsWithin = Callable[[Path, Path], bool]


class WorktreeLifecycle:
    """Create and tear down git worktrees managed by the service."""

    def __init__(
        self,
        base_dir: Path,
        run_git: RunGit,
        parse_worktree_list: ParseWorktreeList,
        is_within: IsWithin,
    ) -> None:
        self._base_dir = base_dir
        self._run_git = run_git
        self._parse_worktree_list_porcelain = parse_worktree_list
        self._is_within = is_within

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
        base = worktree_base_dir if worktree_base_dir is not None else self._base_dir
        base.mkdir(parents=True, exist_ok=True)
        worktree_path = base / job_id
        _gitlog.info("%s start %s", log_label, log_detail, job_id=job_id)
        result = self._run_git(project_path, build_args(worktree_path))
        if result.returncode != 0:
            _gitlog.warning(
                "%s failed %s stderr_len=%d",
                log_label,
                log_detail,
                len(result.stderr),
                job_id=job_id,
            )
            raise RuntimeError(f"{error_label}: {result.stderr.strip()}")
        _gitlog.info("%s ok %s", log_label, log_detail, job_id=job_id)
        return worktree_path

    def prepare_worktree(
        self,
        project_path: Path,
        branch_name: str,
        job_id: str,
        worktree_base_dir: Path | None = None,
    ) -> Path:
        return self._add_worktree(
            project_path,
            job_id,
            lambda worktree_path: ["worktree", "add", "-b", branch_name, str(worktree_path)],
            log_label="prepare_worktree",
            log_detail=f"branch={branch_name}",
            error_label="failed to create worktree",
            worktree_base_dir=worktree_base_dir,
        )

    def prepare_detached_worktree(
        self,
        project_path: Path,
        job_id: str,
        worktree_base_dir: Path | None = None,
        base_branch: str | None = None,
    ) -> Path:
        ref = base_branch if base_branch is not None else "HEAD"
        return self._add_worktree(
            project_path,
            job_id,
            lambda worktree_path: ["worktree", "add", "--detach", str(worktree_path), ref],
            log_label="prepare_detached_worktree",
            log_detail=f"ref={ref}",
            error_label="failed to create detached worktree",
            worktree_base_dir=worktree_base_dir,
        )

    def prepare_branch_worktree(
        self,
        project_path: Path,
        branch_name: str,
        job_id: str,
        worktree_base_dir: Path | None = None,
    ) -> Path:
        return self._add_worktree(
            project_path,
            job_id,
            lambda worktree_path: ["worktree", "add", str(worktree_path), branch_name],
            log_label="prepare_branch_worktree",
            log_detail=f"branch={branch_name}",
            error_label="failed to create branch worktree",
            worktree_base_dir=worktree_base_dir,
        )

    def cleanup_worktree(self, project_path: Path, worktree_path: Path) -> None:
        _gitlog.info("cleanup_worktree start worktree=%s", worktree_path.name)
        result = self._run_git(project_path, ["worktree", "remove", "--force", str(worktree_path)])
        if result.returncode != 0:
            _gitlog.warning("cleanup_worktree failed worktree=%s stderr_len=%d", worktree_path.name, len(result.stderr))
            raise RuntimeError(f"failed to cleanup worktree: {result.stderr.strip()}")
        _gitlog.info("cleanup_worktree ok worktree=%s", worktree_path.name)

    def remove_linked_worktrees_for_branches(
        self, project_path: Path, branch_names: list[str]
    ) -> None:
        if not branch_names:
            return
        want = set(branch_names)
        root = project_path.resolve()
        result = self._run_git(project_path, ["worktree", "list", "--porcelain"])
        if result.returncode != 0:
            raise RuntimeError(f"failed to list worktrees: {result.stderr.strip()}")
        for wt_path, branch in self._parse_worktree_list_porcelain(result.stdout):
            if branch is None or branch not in want:
                continue
            if wt_path.resolve() == root:
                continue
            self.cleanup_worktree(project_path, wt_path)

    def cleanup_managed_worktrees(
        self,
        project_path: Path,
        worktree_base_dir: Path,
        branch_prefix: str = "remote-",
    ) -> int:
        root = project_path.resolve()
        managed_base = worktree_base_dir.resolve()
        rebase_ops_base = (worktree_base_dir / "_rebase_ops").resolve()

        listed = self._run_git(project_path, ["worktree", "list", "--porcelain"])
        if listed.returncode != 0:
            raise RuntimeError(f"failed to list worktrees: {listed.stderr.strip()}")

        cleanup_targets: list[Path] = []
        for wt_path, branch in self._parse_worktree_list_porcelain(listed.stdout):
            resolved = wt_path.resolve()
            if resolved == root:
                continue
            branch_matches = branch is not None and branch.startswith(branch_prefix)
            under_managed_base = self._is_within(resolved, managed_base)
            under_rebase_ops = self._is_within(resolved, rebase_ops_base)
            if branch_matches or under_managed_base or under_rebase_ops:
                cleanup_targets.append(resolved)

        removed = 0
        for target in sorted(set(cleanup_targets), key=lambda p: str(p)):
            self.cleanup_worktree(project_path, target)
            removed += 1

        pruned = self._run_git(project_path, ["worktree", "prune"])
        if pruned.returncode != 0:
            raise RuntimeError(f"failed to prune worktrees: {pruned.stderr.strip()}")
        return removed
