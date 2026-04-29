from __future__ import annotations

import re
import subprocess
import uuid
from pathlib import Path

_SAFE_BRANCH_TOKEN = re.compile(r"^[A-Za-z0-9/._-]+$")


class GitWorktreeService:
    """Git worktree 및 브랜치/원격 조작 Adapter."""

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
        """통합 기준 브랜치 이름(main 또는 master)."""
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
        """기존 API: 새 브랜치로 worktree 생성 (하위 호환)."""
        base = worktree_base_dir if worktree_base_dir is not None else self._base_dir
        base.mkdir(parents=True, exist_ok=True)
        worktree_path = base / job_id
        result = self._run_git(project_path, ["worktree", "add", "-b", branch_name, str(worktree_path)])
        if result.returncode != 0:
            raise RuntimeError(f"failed to create worktree: {result.stderr.strip()}")
        return worktree_path

    def prepare_detached_worktree(
        self,
        project_path: Path,
        job_id: str,
        worktree_base_dir: Path | None = None,
        base_branch: str | None = None,
    ) -> Path:
        """브랜치를 만들지 않고 detached HEAD로 worktree 추가. base_branch 미지정 시 현재 HEAD 기준."""
        ref = base_branch if base_branch is not None else "HEAD"
        base = worktree_base_dir if worktree_base_dir is not None else self._base_dir
        base.mkdir(parents=True, exist_ok=True)
        worktree_path = base / job_id
        result = self._run_git(
            project_path,
            ["worktree", "add", "--detach", str(worktree_path), ref],
        )
        if result.returncode != 0:
            raise RuntimeError(f"failed to create detached worktree: {result.stderr.strip()}")
        return worktree_path

    @staticmethod
    def ensure_worktree_writable(worktree_path: Path) -> None:
        """worktree 디렉터리에 실제 쓰기가 가능한지 확인합니다."""
        probe = worktree_path / ".remote_coder_write_probe"
        try:
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
        except OSError as exc:
            raise RuntimeError(f"worktree is not writable: {worktree_path} ({exc})") from exc

    @staticmethod
    def validate_branch_token(name: str) -> str | None:
        """슬래시 명령 인자용 브랜치 이름 검증. 유효하면 None, 아니면 오류 메시지."""
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
        return result.returncode == 0

    def switch_branch(self, project_path: Path, branch: str) -> None:
        if not self.local_branch_exists(project_path, branch):
            raise RuntimeError(f"로컬 브랜치가 없습니다: {branch}")
        result = self._run_git(project_path, ["switch", branch])
        if result.returncode != 0:
            raise RuntimeError(f"git switch failed: {result.stderr.strip()}")

    def create_branch_in_worktree(self, worktree_path: Path, branch_name: str) -> None:
        """detached worktree에서 새 브랜치로 전환."""
        result = self._run_git(worktree_path, ["switch", "-c", branch_name])
        if result.returncode != 0:
            raise RuntimeError(f"failed to create branch in worktree: {result.stderr.strip()}")

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

    def push_branch(self, project_path: Path, remote: str, branch: str) -> None:
        """원격에 브랜치 push (-u 설정)."""
        result = self._run_git(project_path, ["push", "-u", remote, branch])
        if result.returncode != 0:
            raise RuntimeError(f"git push failed: {result.stderr.strip()}")

    def cleanup_worktree(self, project_path: Path, worktree_path: Path) -> None:
        result = self._run_git(project_path, ["worktree", "remove", "--force", str(worktree_path)])
        if result.returncode != 0:
            raise RuntimeError(f"failed to cleanup worktree: {result.stderr.strip()}")

    def checkout_integrate_branch(self, project_path: Path) -> str:
        """main/master 중 존재하는 브랜치로 checkout."""
        name = self.resolve_integrate_branch(project_path)
        result = self._run_git(project_path, ["checkout", name])
        if result.returncode != 0:
            raise RuntimeError(f"checkout {name} failed: {result.stderr.strip()}")
        return name

    def format_local_branches(self, project_path: Path) -> str:
        """로컬 브랜치 전체 목록(git branch 기본 출력, 현재 브랜치에 * 표시)."""
        result = self._run_git(project_path, ["branch", "--sort=refname"])
        if result.returncode != 0:
            raise RuntimeError(f"failed to list local branches: {result.stderr.strip()}")
        text = result.stdout.strip()
        return text if text else "(로컬 브랜치 없음)"

    def format_remote_branches_for_remote(self, project_path: Path, remote: str) -> str:
        """지정 원격(remote) 아래 추적 브랜치만 한 줄씩 정리."""
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

    @staticmethod
    def _branch_name_from_git_branch_output_line(line: str) -> str:
        """`git branch` 한 줄에서 마커 제거. `*` 현재 브랜치, `+` 다른 worktree checkout."""
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
        """`git worktree list --porcelain` 파싱. 각 항목은 (경로, 브랜치 짧은 이름 또는 detached면 None)."""
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
        """삭제할 브랜치가 다른 linked worktree에 checkout되어 있으면 먼저 제거합니다."""
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

    def list_remote_branches_matching(self, project_path: Path, remote: str, prefix: str) -> list[str]:
        """
        실제 원격 저장소의 브랜치를 조회합니다.
        `git branch -r`은 로컬 remote-tracking ref만 보여 캐시가 오래되면 누락될 수 있어,
        `git ls-remote --heads`를 사용합니다.

        ref 패턴 인자(`refs/heads/remote-*`)는 원격/Git 조합에 따라 빈 결과만 돌아오는 경우가 있어,
        헤드 전체를 받은 뒤 접두사로 필터링합니다.
        """
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

    def rebase_branch_onto_main_and_merge(
        self,
        project_path: Path,
        branch: str,
        remote: str,
        worktree_ops_base: Path,
    ) -> str:
        """
        feature 브랜치를 origin/main(또는 master) 기준으로 rebase한 뒤,
        로컬 main을 fast-forward merge하고 origin에 push합니다.
        반환: 요약 메시지(사용자 알림용).
        """
        main_branch = self.resolve_integrate_branch(project_path)
        fetch_main = self._run_git(project_path, ["fetch", remote, main_branch])
        if fetch_main.returncode != 0:
            raise RuntimeError(f"git fetch {remote} {main_branch} failed: {fetch_main.stderr.strip()}")

        fetch_branch = self._run_git(project_path, ["fetch", remote, branch])
        if fetch_branch.returncode != 0:
            raise RuntimeError(f"git fetch {remote} {branch} failed: {fetch_branch.stderr.strip()}")

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

        return (
            f"rebase 완료: 브랜치 `{branch}`를 `{remote}/{main_branch}` 기준으로 rebase 후 "
            f"`{main_branch}`에 fast-forward 병합하고 `{remote}`에 push했습니다."
        )
