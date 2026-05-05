from __future__ import annotations

import re
import subprocess
import uuid
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

    @staticmethod
    def _remote_branch_ref(remote: str, branch: str) -> str:
        return f"{remote}/{branch}"

    def resolve_integrate_branch(self, project_path: Path) -> str:
        for candidate in ("main", "master"):
            result = self._run_git(project_path, ["rev-parse", "--verify", candidate])
            if result.returncode == 0:
                return candidate
        raise RuntimeError(
            "통합 브랜치(main 또는 master)를 찾을 수 없습니다. 저장소에 main 또는 master가 있어야 합니다."
        )

    def prepare_worktree(
        self,
        project_path: Path,
        branch_name: str,
        job_id: str,
        worktree_base_dir: Path | None = None,
    ) -> Path:
        base = worktree_base_dir if worktree_base_dir is not None else self._base_dir
        base.mkdir(parents=True, exist_ok=True)
        worktree_path = base / job_id
        _gitlog.info("prepare_worktree start branch=%s", branch_name, job_id=job_id)
        result = self._run_git(project_path, ["worktree", "add", "-b", branch_name, str(worktree_path)])
        if result.returncode != 0:
            _gitlog.warning(
                "prepare_worktree failed branch=%s stderr_len=%d",
                branch_name,
                len(result.stderr),
                job_id=job_id,
            )
            raise RuntimeError(f"failed to create worktree: {result.stderr.strip()}")
        _gitlog.info("prepare_worktree ok branch=%s", branch_name, job_id=job_id)
        return worktree_path

    def prepare_detached_worktree(
        self,
        project_path: Path,
        job_id: str,
        worktree_base_dir: Path | None = None,
        base_branch: str | None = None,
    ) -> Path:
        ref = base_branch if base_branch is not None else "HEAD"
        base = worktree_base_dir if worktree_base_dir is not None else self._base_dir
        base.mkdir(parents=True, exist_ok=True)
        worktree_path = base / job_id
        _gitlog.info("prepare_detached_worktree start ref=%s", ref, job_id=job_id)
        result = self._run_git(
            project_path,
            ["worktree", "add", "--detach", str(worktree_path), ref],
        )
        if result.returncode != 0:
            _gitlog.warning(
                "prepare_detached_worktree failed ref=%s stderr_len=%d",
                ref,
                len(result.stderr),
                job_id=job_id,
            )
            raise RuntimeError(f"failed to create detached worktree: {result.stderr.strip()}")
        _gitlog.info("prepare_detached_worktree ok ref=%s", ref, job_id=job_id)
        return worktree_path

    def prepare_branch_worktree(
        self,
        project_path: Path,
        branch_name: str,
        job_id: str,
        worktree_base_dir: Path | None = None,
    ) -> Path:
        base = worktree_base_dir if worktree_base_dir is not None else self._base_dir
        base.mkdir(parents=True, exist_ok=True)
        worktree_path = base / job_id
        _gitlog.info("prepare_branch_worktree start branch=%s", branch_name, job_id=job_id)
        result = self._run_git(project_path, ["worktree", "add", str(worktree_path), branch_name])
        if result.returncode != 0:
            _gitlog.warning(
                "prepare_branch_worktree failed branch=%s stderr_len=%d",
                branch_name,
                len(result.stderr),
                job_id=job_id,
            )
            raise RuntimeError(f"failed to create branch worktree: {result.stderr.strip()}")
        _gitlog.info("prepare_branch_worktree ok branch=%s", branch_name, job_id=job_id)
        return worktree_path

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
            return "브랜치 이름이 비었거나 너무 깁니다."
        if ".." in name or name.startswith("-"):
            return "허용되지 않는 브랜치 이름입니다."
        if not _SAFE_BRANCH_TOKEN.match(name):
            return "브랜치 이름은 영문, 숫자, /, ., _, - 만 사용할 수 있습니다."
        return None

    def get_current_branch(self, project_path: Path) -> str:
        """checkout 중인 로컬 브랜치 이름. detached면 안내 문구."""
        result = self._run_git(project_path, ["branch", "--show-current"])
        if result.returncode != 0:
            raise RuntimeError(f"failed to read current branch: {result.stderr.strip()}")
        name = result.stdout.strip()
        if name:
            return name
        return "(detached HEAD — 브랜치 이름 없음)"

    def local_branch_exists(self, project_path: Path, branch: str) -> bool:
        result = self._run_git(project_path, ["show-ref", "--verify", f"refs/heads/{branch}"])
        _gitlog.info("local_branch_exists branch=%s exists=%s", branch, result.returncode == 0)
        return result.returncode == 0

    def switch_branch(self, project_path: Path, branch: str) -> None:
        if not self.local_branch_exists(project_path, branch):
            raise RuntimeError(f"로컬 브랜치가 없습니다: {branch}")
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
        return text if text else "(로컬 브랜치 없음)"

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
        return "\n".join(lines) if lines else f"({remote} 원격 브랜치 없음)"

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
        # `*` 현재 브랜치, `+` 다른 worktree checkout 마커를 제거합니다.
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
        # 삭제 대상 브랜치가 다른 linked worktree에 체크아웃되어 있으면 `branch -D`가 거부되므로 선제거합니다.
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
        # 프로젝트 루트 worktree는 보존하고, branch_prefix 또는 managed/_rebase_ops 경로 하위만 정리합니다.
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
        # `git branch -r`은 로컬 캐시 의존이라 누락될 수 있어 `ls-remote --heads`로 직접 조회합니다.
        # ref 패턴(`refs/heads/remote-*`) 인자는 원격/Git 조합에 따라 빈 결과만 돌려주는 경우가 있어 헤드 전체를 받은 뒤 접두사로 필터링합니다.
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
            raise RuntimeError(f"git fetch {remote} 실패: {fetch_res.stderr.strip()}")

        current = self.get_current_branch(project_path)
        if not current.startswith("("):
            pull_res = self._run_git(project_path, ["pull", remote, current])
            if pull_res.returncode != 0:
                # 충돌 가능성이 있어 merge abort 후 사용자에게 원인을 다시 던집니다.
                self._run_git(project_path, ["merge", "--abort"])
                raise RuntimeError(f"git pull {remote} {current} 실패 (충돌 가능성): {pull_res.stderr.strip()}")
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

        summary = f"원격({remote})에서 모든 정보를 가져왔습니다."
        if not current.startswith("("):
            summary += f" 현재 브랜치({current})를 업데이트했습니다."
        if updated_count > 0:
            summary += f" 추가로 {updated_count}개의 로컬 브랜치를 fast-forward 업데이트했습니다."

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
        fetch_main = self._run_git(project_path, ["fetch", remote, main_branch])
        if fetch_main.returncode != 0:
            raise RuntimeError(f"git fetch {remote} {main_branch} failed: {fetch_main.stderr.strip()}")

        fetch_branch = self._run_git(project_path, ["fetch", remote, branch])
        if fetch_branch.returncode != 0:
            raise RuntimeError(f"git fetch {remote} {branch} failed: {fetch_branch.stderr.strip()}")

        # 같은 브랜치가 Job worktree 등에 checkout되어 있으면 `worktree add -B`가 실패합니다.
        self.remove_linked_worktrees_for_branches(project_path, [branch])

        worktree_ops_base.mkdir(parents=True, exist_ok=True)
        op_id = f"_rebase_{uuid.uuid4().hex[:8]}"
        op_path = worktree_ops_base / op_id

        add = self._run_git(
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
        )
        if add.returncode != 0:
            raise RuntimeError(f"worktree add for rebase failed: {add.stderr.strip()}")

        try:
            rb = self._run_git(op_path, ["rebase", self._remote_branch_ref(remote, main_branch)])
            if rb.returncode != 0:
                abort = self._run_git(op_path, ["rebase", "--abort"])
                _ = abort
                raise RuntimeError(f"git rebase failed: {rb.stderr.strip()}")

            push_feat = self._run_git(op_path, ["push", "--force-with-lease", remote, branch])
            if push_feat.returncode != 0:
                raise RuntimeError(f"git push feature after rebase failed: {push_feat.stderr.strip()}")

            checkout_main = self._run_git(project_path, ["checkout", main_branch])
            if checkout_main.returncode != 0:
                raise RuntimeError(f"checkout {main_branch} failed: {checkout_main.stderr.strip()}")

            pull_main = self._run_git(project_path, ["pull", "--ff-only", remote, main_branch])
            if pull_main.returncode != 0:
                raise RuntimeError(f"git pull --ff-only {remote} {main_branch} failed: {pull_main.stderr.strip()}")

            merge_ff = self._run_git(project_path, ["merge", "--ff-only", branch])
            if merge_ff.returncode != 0:
                raise RuntimeError(
                    f"fast-forward merge into {main_branch} failed (non-ff?): {merge_ff.stderr.strip()}"
                )

            push_main = self._run_git(project_path, ["push", remote, main_branch])
            if push_main.returncode != 0:
                raise RuntimeError(f"git push {remote} {main_branch} failed: {push_main.stderr.strip()}")
        finally:
            rm = self._run_git(project_path, ["worktree", "remove", "--force", str(op_path)])
            if rm.returncode != 0:
                raise RuntimeError(f"failed to remove rebase worktree: {rm.stderr.strip()}")

        summary = (
            f"rebase 완료: 브랜치 `{branch}`를 `{remote}/{main_branch}` 기준으로 rebase 후 "
            f"`{main_branch}`에 fast-forward 병합하고 `{remote}`에 push했습니다."
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
        raise RuntimeError(f"gh pr create 실패: {stderr or stdout}")
