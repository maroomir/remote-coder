from __future__ import annotations

import re
import subprocess
import uuid
from collections.abc import Callable
from pathlib import Path

from app.monitoring.events import EventLogger

_SAFE_BRANCH_TOKEN = re.compile(r"^[A-Za-z0-9/._-]+$")

_gitlog = EventLogger("app.git.service", "git.operation")


class GitWorktreeService:
    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir
        self._base_dir.mkdir(parents=True, exist_ok=True)

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
        for candidate in ("main", "master"):
            result = self._run_git(project_path, ["rev-parse", "--verify", candidate])
            if result.returncode == 0:
                return candidate
        raise RuntimeError(
            "No integration branch (main or master). The repository needs main or master."
        )

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

    def switch_branch(self, project_path: Path, branch: str) -> None:
        if not self.local_branch_exists(project_path, branch):
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

    def find_linked_worktree_for_branch(self, project_path: Path, branch_name: str) -> Path | None:
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
        checked_out = any(branch == branch_name for _, branch in self._parse_worktree_list_porcelain(result.stdout))
        _gitlog.info("branch_is_checked_out branch=%s checked_out=%s", branch_name, checked_out)
        return checked_out

    def collect_changes(self, worktree_path: Path) -> list[str]:
        result = self._run_git(worktree_path, ["status", "--porcelain"])
        if result.returncode != 0:
            _gitlog.warning("collect_changes failed stderr_len=%d", len(result.stderr))
            raise RuntimeError(f"failed to collect changes: {result.stderr.strip()}")
        files: list[str] = []
        for line in result.stdout.splitlines():
            if len(line) > 3:
                files.append(line[3:].strip())
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

    def push_branch(self, project_path: Path, remote: str, branch: str) -> None:
        _gitlog.info("push_branch start remote=%s branch=%s", remote, branch)
        result = self._run_git(project_path, ["push", "-u", remote, branch])
        if result.returncode != 0:
            _gitlog.warning("push_branch failed remote=%s branch=%s stderr_len=%d", remote, branch, len(result.stderr))
            raise RuntimeError(f"git push failed: {result.stderr.strip()}")
        _gitlog.info("push_branch ok remote=%s branch=%s", remote, branch)

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

    def cleanup_worktree(self, project_path: Path, worktree_path: Path) -> None:
        _gitlog.info("cleanup_worktree start worktree=%s", worktree_path.name)
        result = self._run_git(project_path, ["worktree", "remove", "--force", str(worktree_path)])
        if result.returncode != 0:
            _gitlog.warning("cleanup_worktree failed worktree=%s stderr_len=%d", worktree_path.name, len(result.stderr))
            raise RuntimeError(f"failed to cleanup worktree: {result.stderr.strip()}")
        _gitlog.info("cleanup_worktree ok worktree=%s", worktree_path.name)

    def checkout_integrate_branch(self, project_path: Path) -> str:
        name = self.resolve_integrate_branch(project_path)
        result = self._run_git(project_path, ["checkout", name])
        if result.returncode != 0:
            raise RuntimeError(f"checkout {name} failed: {result.stderr.strip()}")
        return name

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

    def count_local_branches(self, project_path: Path) -> int:
        result = self._run_git(project_path, ["branch", "--format=%(refname:short)"])
        if result.returncode != 0:
            raise RuntimeError(f"failed to count local branches: {result.stderr.strip()}")
        return len([ln for ln in result.stdout.splitlines() if ln.strip()])

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

    def list_worktree_entries(self, project_path: Path) -> list[tuple[Path, str | None]]:
        result = self._run_git(project_path, ["worktree", "list", "--porcelain"])
        if result.returncode != 0:
            raise RuntimeError(f"failed to list worktrees: {result.stderr.strip()}")
        return self._parse_worktree_list_porcelain(result.stdout)

    @staticmethod
    def _branch_name_from_git_branch_output_line(line: str) -> str:
        name = line.strip()
        while name and name[0] in "+*":
            name = name[1:].lstrip()
        return name

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

    def list_remote_branches_matching(self, project_path: Path, remote: str, prefix: str) -> list[str]:
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

        current = self.get_current_branch(project_path)
        if not current.startswith("("):
            pull_res = self._run_git(project_path, ["pull", remote, current])
            if pull_res.returncode != 0:
                self._run_git(project_path, ["merge", "--abort"])
                raise RuntimeError(f"git pull {remote} {current} failed (possible conflict): {pull_res.stderr.strip()}")
        else:
            _gitlog.info("pull_repository: detached HEAD, skipping pull for current branch")

        wt_entries = self.list_worktree_entries(project_path)
        local_branches = self.list_local_branches(project_path)

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
        main_branch = self.resolve_integrate_branch(project_path)
        self._run_git_checked(
            project_path, ["fetch", remote, main_branch], f"git fetch {remote} {main_branch} failed"
        )
        self._run_git_checked(
            project_path, ["fetch", remote, branch], f"git fetch {remote} {branch} failed"
        )

        self.remove_linked_worktrees_for_branches(project_path, [branch])

        worktree_ops_base.mkdir(parents=True, exist_ok=True)
        op_id = f"_rebase_{uuid.uuid4().hex[:8]}"
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

    def create_github_pr(
        self,
        project_path: Path,
        branch: str,
        base_branch: str,
        title: str,
        body: str,
    ) -> str:
        _gitlog.info("create_github_pr branch=%s base=%s", branch, base_branch)
        result = subprocess.run(
            ["gh", "pr", "create", "--base", base_branch, "--head", branch,
             "--title", title, "--body", body],
            cwd=project_path,
            capture_output=True,
            text=True,
            check=False,
            shell=False,
        )
        if result.returncode == 0:
            url = result.stdout.strip()
            _gitlog.info("create_github_pr created url=%s", url)
            return url
        stderr = result.stderr.strip()
        stdout = result.stdout.strip()
        combined = (stderr + stdout).lower()
        if "already exists" in combined:
            view = subprocess.run(
                ["gh", "pr", "view", branch, "--json", "url", "--jq", ".url"],
                cwd=project_path,
                capture_output=True,
                text=True,
                check=False,
                shell=False,
            )
            if view.returncode == 0 and view.stdout.strip():
                existing_url = view.stdout.strip()
                _gitlog.info("create_github_pr already exists url=%s", existing_url)
                return existing_url
        raise RuntimeError(f"gh pr create failed: {stderr or stdout}")
