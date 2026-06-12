from __future__ import annotations

from pathlib import Path

from app.git.service import GitWorktreeService
from app.telegram.tables import render_table


TELEGRAM_SAFE_LEN = 3800


def format_branch_monitor(
    git: GitWorktreeService,
    root: Path,
    remote: str,
    project_name: str,
    max_len: int = TELEGRAM_SAFE_LEN,
) -> str:
    try:
        current = git.get_current_branch(root)
        local_n = git.count_local_branches(root)
        remote_n = git.count_remote_branches_for_remote(root, remote)
        local_block = git.format_local_branches(root)
        remote_block = git.format_remote_branches_for_remote(root, remote)
    except RuntimeError as exc:
        return f"/monitor branch failed: {exc}"

    header_rows = [
        ("Project", project_name),
        ("root", str(root)),
        ("Remote", remote),
        ("Current checkout", current),
        ("Local branches", str(local_n)),
        (f"{remote} remote-tracking branches", str(remote_n)),
    ]
    header = "Branch monitor\n" + render_table(header_rows, headers=("metric", "value")) + "\n\n"
    body = f"[Local]\n{local_block}\n\n[{remote} remote]\n{remote_block}"
    text = header + body
    if len(text) > max_len:
        text = text[:max_len].rstrip() + "\n\n...(truncated for message length)"
    return text


def format_worktree_monitor(
    git: GitWorktreeService,
    project_path: Path,
    worktree_base_dir: Path,
    project_name: str,
    branch_prefix: str = "remote-",
    max_detail: int = 40,
) -> str:
    try:
        entries = git.list_worktree_entries(project_path)
    except RuntimeError as exc:
        return f"/monitor worktrees failed: {exc}"

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
        extra = f"\n...({len(entries) - max_detail} more omitted)"

    header_rows = [
        ("Project", project_name),
        ("root", str(root)),
        ("Managed base directory", str(managed_base)),
        ("Total worktrees", str(len(entries))),
        ("Detached worktrees", str(detached_n)),
        ("Managed candidates", str(managed_n)),
    ]
    lines = [
        "Worktree monitor",
        render_table(header_rows, headers=("metric", "value")),
        "",
        "[Entries]",
        *detail_lines,
        extra,
    ]
    return "\n".join(lines).strip()
