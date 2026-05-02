"""Git 브랜치·worktree 모니터링 (읽기 전용)."""

from __future__ import annotations

from pathlib import Path

from app.git.service import GitWorktreeService


TELEGRAM_SAFE_LEN = 3800


def format_branch_monitor(
    git: GitWorktreeService,
    root: Path,
    remote: str,
    project_name: str,
    max_len: int = TELEGRAM_SAFE_LEN,
) -> str:
    """로컬·원격 브랜치 요약 및 목록(적용 프로젝트 기준)."""
    try:
        current = git.get_current_branch(root)
        local_n = git.count_local_branches(root)
        remote_n = git.count_remote_branches_for_remote(root, remote)
        local_block = git.format_local_branches(root)
        remote_block = git.format_remote_branches_for_remote(root, remote)
    except RuntimeError as exc:
        return f"/monitor branch 실패: {exc}"

    header = (
        f"브랜치 모니터\n"
        f"프로젝트: {project_name}\n"
        f"root: {root}\n"
        f"원격 이름: {remote}\n"
        f"현재 checkout: {current}\n"
        f"로컬 브랜치 수: {local_n}\n"
        f"{remote} 원격 추적 브랜치 수: {remote_n}\n\n"
    )
    body = f"[로컬]\n{local_block}\n\n[{remote} 원격]\n{remote_block}"
    text = header + body
    if len(text) > max_len:
        text = text[:max_len].rstrip() + "\n\n...(메시지 길이 제한으로 생략)"
    return text


def format_worktree_monitor(
    git: GitWorktreeService,
    project_path: Path,
    worktree_base_dir: Path,
    project_name: str,
    branch_prefix: str = "remote-",
    max_detail: int = 40,
) -> str:
    """`git worktree list --porcelain` 기반 요약."""
    try:
        entries = git.list_worktree_entries(project_path)
    except RuntimeError as exc:
        return f"/monitor worktrees 실패: {exc}"

    root = project_path.resolve()
    managed_base = worktree_base_dir.resolve()
    rebase_ops_base = (worktree_base_dir / "_rebase_ops").resolve()

    detached_n = 0
    managed_n = 0
    detail_lines: list[str] = []

    for wt_path, branch in entries:
        resolved = wt_path.resolve()
        is_root = resolved == root
        branch_matches = branch is not None and branch.startswith(branch_prefix)
        under_managed = GitWorktreeService._is_within(resolved, managed_base)
        under_rebase = GitWorktreeService._is_within(resolved, rebase_ops_base)
        is_managed = (not is_root) and (branch_matches or under_managed or under_rebase)
        if branch is None:
            detached_n += 1
        if is_managed:
            managed_n += 1

        if len(detail_lines) < max_detail:
            b_label = branch if branch is not None else "(detached)"
            tags: list[str] = []
            if is_root:
                tags.append("main worktree")
            if is_managed:
                tags.append("managed")
            tag_s = f" [{' '.join(tags)}]" if tags else ""
            detail_lines.append(f"- {wt_path} → {b_label}{tag_s}")

    extra = ""
    if len(entries) > max_detail:
        extra = f"\n...(외 {len(entries) - max_detail}개 생략)"

    lines = [
        "워크트리 모니터",
        f"프로젝트: {project_name}",
        f"root: {root}",
        f"관리 기준 디렉터리(worktree_base): {managed_base}",
        f"총 worktree 수: {len(entries)}",
        f"detached 수: {detached_n}",
        f"managed 후보 수(remote-*·base·_rebase_ops): {managed_n}",
        "",
        "[항목]",
        *detail_lines,
        extra,
    ]
    return "\n".join(lines).strip()
