from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from app.monitoring.events import EventLogger

if TYPE_CHECKING:
    import subprocess

    from app.git.branch_query import BranchQuery
    from app.git.worktree_lifecycle import WorktreeLifecycle
    from app.git.worktree_listing import WorktreeListing

_gitlog = EventLogger("app.git.service", "git.operation")

RunGit = Callable[[Path, list[str]], "subprocess.CompletedProcess[str]"]
RunGitChecked = Callable[[Path, list[str], str], "subprocess.CompletedProcess[str]"]
RunGh = Callable[[Path, list[str]], "subprocess.CompletedProcess[str]"]
RemoteBranchRef = Callable[[str, str], str]
NewRebaseOperationId = Callable[[], str]


class RemoteOps:
    """Remote-facing git operations: push, pull, delete, rebase, cherry-pick, PR, switch."""

    def __init__(
        self,
        run_git: RunGit,
        run_git_checked: RunGitChecked,
        run_gh: RunGh,
        remote_branch_ref: RemoteBranchRef,
        new_rebase_operation_id: NewRebaseOperationId,
        branch_query: BranchQuery,
        worktree_listing: WorktreeListing,
        worktree_lifecycle: WorktreeLifecycle,
    ) -> None:
        self._run_git = run_git
        self._run_git_checked = run_git_checked
        self._run_gh = run_gh
        self._remote_branch_ref = remote_branch_ref
        self._new_rebase_operation_id = new_rebase_operation_id
        self._branch_query = branch_query
        self._worktree_listing = worktree_listing
        self._worktree_lifecycle = worktree_lifecycle

    def switch_branch(self, project_path: Path, branch: str) -> None:
        if not self._branch_query.local_branch_exists(project_path, branch):
            raise RuntimeError(f"No local branch: {branch}")
        result = self._run_git(project_path, ["switch", branch])
        if result.returncode != 0:
            raise RuntimeError(f"git switch failed: {result.stderr.strip()}")

    def create_branch_in_worktree(self, worktree_path: Path, branch_name: str) -> None:
        _gitlog.info("create_branch_in_worktree start branch=%s", branch_name)
        result = self._run_git(worktree_path, ["switch", "-c", branch_name])
        if result.returncode != 0:
            _gitlog.warning("create_branch_in_worktree failed branch=%s stderr_len=%d", branch_name, len(result.stderr))
            raise RuntimeError(f"failed to create branch in worktree: {result.stderr.strip()}")
        _gitlog.info("create_branch_in_worktree ok branch=%s", branch_name)

    def push_branch(self, project_path: Path, remote: str, branch: str) -> None:
        _gitlog.info("push_branch start remote=%s branch=%s", remote, branch)
        result = self._run_git(project_path, ["push", "-u", remote, branch])
        if result.returncode != 0:
            _gitlog.warning("push_branch failed remote=%s branch=%s stderr_len=%d", remote, branch, len(result.stderr))
            raise RuntimeError(f"git push failed: {result.stderr.strip()}")
        _gitlog.info("push_branch ok remote=%s branch=%s", remote, branch)

    def push_branch_force_with_lease(self, project_path: Path, remote: str, branch: str) -> None:
        _gitlog.info("push_branch_force_with_lease start remote=%s branch=%s", remote, branch)
        result = self._run_git(
            project_path,
            ["push", "--force-with-lease", remote, branch],
        )
        if result.returncode != 0:
            _gitlog.warning(
                "push_branch_force_with_lease failed remote=%s branch=%s stderr_len=%d",
                remote,
                branch,
                len(result.stderr),
            )
            raise RuntimeError(f"git push --force-with-lease failed: {result.stderr.strip()}")
        _gitlog.info("push_branch_force_with_lease ok remote=%s branch=%s", remote, branch)

    def checkout_integrate_branch(self, project_path: Path) -> str:
        name = self._branch_query.resolve_integrate_branch(project_path)
        result = self._run_git(project_path, ["checkout", name])
        if result.returncode != 0:
            raise RuntimeError(f"checkout {name} failed: {result.stderr.strip()}")
        return name

    def delete_local_branches(self, project_path: Path, branches: list[str]) -> None:
        for name in branches:
            result = self._run_git(project_path, ["branch", "-D", name])
            if result.returncode != 0:
                raise RuntimeError(f"failed to delete local branch {name}: {result.stderr.strip()}")

    def delete_remote_branches(self, project_path: Path, remote: str, branches: list[str]) -> None:
        for name in branches:
            result = self._run_git(project_path, ["push", remote, "--delete", name])
            if result.returncode != 0:
                raise RuntimeError(f"failed to delete remote branch {name}: {result.stderr.strip()}")

    def pull_repository(self, project_path: Path, remote: str) -> str:
        _gitlog.info("pull_repository start remote=%s", remote)

        fetch_res = self._run_git(project_path, ["fetch", remote, "--prune"])
        if fetch_res.returncode != 0:
            raise RuntimeError(f"git fetch {remote} failed: {fetch_res.stderr.strip()}")

        current = self._branch_query.get_current_branch(project_path)
        if not current.startswith("("):
            pull_res = self._run_git(project_path, ["pull", remote, current])
            if pull_res.returncode != 0:
                self._run_git(project_path, ["merge", "--abort"])
                raise RuntimeError(f"git pull {remote} {current} failed (possible conflict): {pull_res.stderr.strip()}")
        else:
            _gitlog.info("pull_repository: detached HEAD, skipping pull for current branch")

        wt_entries = self._worktree_listing.list_worktree_entries(project_path)
        local_branches = self._branch_query.list_local_branches(project_path)

        updated_count = 0
        for branch in local_branches:
            if branch == current:
                continue

            if any(b == branch for _, b in wt_entries):
                continue

            # `fetch remote b:b`는 로컬이 원격의 조상일 때만 성공하므로, 비-FF 분기는 자연스럽게 건너뜁니다.
            ff_res = self._run_git(project_path, ["fetch", remote, f"{branch}:{branch}"])
            if ff_res.returncode == 0:
                updated_count += 1

        summary = f"Fetched updates from remote {remote}."
        if not current.startswith("("):
            summary += f" Updated current branch ({current})."
        if updated_count > 0:
            summary += f" Fast-forward updated {updated_count} additional local branch(es)."

        _gitlog.info("pull_repository done: %s", summary)
        return summary

    def rebase_branch_onto_main_and_merge(
        self,
        project_path: Path,
        branch: str,
        remote: str,
        worktree_ops_base: Path,
    ) -> str:
        _gitlog.info("rebase_branch_onto_main_and_merge start branch=%s", branch)
        main_branch = self._branch_query.resolve_integrate_branch(project_path)
        self._run_git_checked(
            project_path, ["fetch", remote, main_branch], f"git fetch {remote} {main_branch} failed"
        )
        self._run_git_checked(
            project_path, ["fetch", remote, branch], f"git fetch {remote} {branch} failed"
        )

        self._worktree_lifecycle.remove_linked_worktrees_for_branches(project_path, [branch])

        worktree_ops_base.mkdir(parents=True, exist_ok=True)
        op_id = self._new_rebase_operation_id()
        op_path = worktree_ops_base / op_id

        self._run_git_checked(
            project_path,
            [
                "worktree",
                "add",
                "-f",
                "-B",
                branch,
                str(op_path),
                self._remote_branch_ref(remote, branch),
                "--track",
            ],
            "worktree add for rebase failed",
        )

        try:
            rb = self._run_git(op_path, ["rebase", self._remote_branch_ref(remote, main_branch)])
            if rb.returncode != 0:
                self._run_git(op_path, ["rebase", "--abort"])
                raise RuntimeError(f"git rebase failed: {rb.stderr.strip()}")

            self._run_git_checked(
                op_path,
                ["push", "--force-with-lease", remote, branch],
                "git push feature after rebase failed",
            )
            self._run_git_checked(
                project_path, ["checkout", main_branch], f"checkout {main_branch} failed"
            )
            self._run_git_checked(
                project_path,
                ["pull", "--ff-only", remote, main_branch],
                f"git pull --ff-only {remote} {main_branch} failed",
            )
            self._run_git_checked(
                project_path,
                ["merge", "--ff-only", branch],
                f"fast-forward merge into {main_branch} failed (non-ff?)",
            )
            self._run_git_checked(
                project_path, ["push", remote, main_branch], f"git push {remote} {main_branch} failed"
            )
        finally:
            self._run_git_checked(
                project_path,
                ["worktree", "remove", "--force", str(op_path)],
                "failed to remove rebase worktree",
            )

        summary = (
            f"Rebase complete: rebased `{branch}` onto `{remote}/{main_branch}`, "
            f"fast-forward merged into `{main_branch}`, pushed to `{remote}`."
        )
        _gitlog.info("rebase_branch_onto_main_and_merge done branch=%s", branch)
        return summary

    def cherry_pick_branch_onto_main(
        self,
        project_path: Path,
        branch: str,
        remote: str,
        worktree_ops_base: Path,
    ) -> str:
        """Cherry-pick the branch tip's commit onto main and push, in an isolated worktree.

        Operates on a fresh worktree checked out from the up-to-date integration branch so the
        project's main checkout is never disturbed. Aborts and cleans up on any conflict.
        """
        _gitlog.info("cherry_pick_branch_onto_main start branch=%s", branch)
        main_branch = self._branch_query.resolve_integrate_branch(project_path)
        self._run_git_checked(
            project_path, ["fetch", remote, main_branch], f"git fetch {remote} {main_branch} failed"
        )
        self._run_git_checked(
            project_path, ["fetch", remote, branch], f"git fetch {remote} {branch} failed"
        )

        commit_result = self._run_git(
            project_path, ["rev-parse", self._remote_branch_ref(remote, branch)]
        )
        if commit_result.returncode != 0:
            raise RuntimeError(
                f"failed to resolve {remote}/{branch}: {commit_result.stderr.strip()}"
            )
        commit_sha = commit_result.stdout.strip()

        worktree_ops_base.mkdir(parents=True, exist_ok=True)
        op_id = self._new_rebase_operation_id()
        op_path = worktree_ops_base / op_id

        self._run_git_checked(
            project_path,
            [
                "worktree",
                "add",
                "--detach",
                str(op_path),
                self._remote_branch_ref(remote, main_branch),
            ],
            "worktree add for cherry-pick failed",
        )

        try:
            cp = self._run_git(op_path, ["cherry-pick", commit_sha])
            if cp.returncode != 0:
                self._run_git(op_path, ["cherry-pick", "--abort"])
                raise RuntimeError(f"git cherry-pick failed (conflict?): {cp.stderr.strip()}")

            self._run_git_checked(
                op_path,
                ["push", remote, f"HEAD:{main_branch}"],
                f"git push cherry-pick to {remote}/{main_branch} failed",
            )
        finally:
            # Best-effort cleanup: never let a removal failure mask the cherry-pick error above.
            cleanup = self._run_git(project_path, ["worktree", "remove", "--force", str(op_path)])
            if cleanup.returncode != 0:
                _gitlog.warning(
                    "failed to remove cherry-pick worktree stderr_len=%d", len(cleanup.stderr)
                )

        short_sha = commit_sha[:7]
        summary = (
            f"Cherry-pick complete: applied `{short_sha}` from `{branch}` "
            f"onto `{main_branch}` and pushed to `{remote}`."
        )
        _gitlog.info("cherry_pick_branch_onto_main done branch=%s", branch)
        return summary

    def create_github_pr(
        self,
        project_path: Path,
        branch: str,
        base_branch: str,
        title: str,
        body: str,
    ) -> str:
        _gitlog.info("create_github_pr branch=%s base=%s", branch, base_branch)
        result = self._run_gh(
            project_path,
            ["gh", "pr", "create", "--base", base_branch, "--head", branch,
             "--title", title, "--body", body],
        )
        if result.returncode == 0 and result.stdout.strip():
            url = result.stdout.strip()
            _gitlog.info("create_github_pr created url=%s", url)
            return url
        stderr = result.stderr.strip()
        stdout = result.stdout.strip()
        combined = (stderr + stdout).lower()
        if "already exists" in combined:
            view = self._run_gh(
                project_path,
                ["gh", "pr", "view", branch, "--json", "url", "--jq", ".url"],
            )
            if view.returncode == 0 and view.stdout.strip():
                existing_url = view.stdout.strip()
                _gitlog.info("create_github_pr already exists url=%s", existing_url)
                return existing_url
            detail = view.stderr.strip() or view.stdout.strip() or "existing PR URL was not returned"
            raise RuntimeError(
                f"gh pr view failed: {detail}. Check `gh auth status` and repository access."
            )
        detail = stderr or stdout or "no output"
        raise RuntimeError(
            f"gh pr create failed: {detail}. Check `gh auth status` and repository access."
        )
