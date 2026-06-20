"""Regression + characterization tests for app.git.service.collect_changes.

Tester 3 (AI Runners & Git Automation). These probe how the changed-files list
that flows into F6 (commit message scope, result notification "수정 파일 목록",
and the stored job result) is built from `git status --porcelain`.

CONFIRMED BUG (xfail): a staged rename emits a single porcelain line
`R  old -> new`; `collect_changes` does `line[3:].strip()` and therefore stores
the literal string `old -> new` (and `"old" -> "new"` when paths contain
spaces) as if it were one file path. The new path is never reported as a clean
path, which corrupts changed_files reporting and commit scope inference.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.git.service import GitWorktreeService


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    for args in (
        ["init", "-q"],
        ["config", "user.email", "t@example.com"],
        ["config", "user.name", "tester"],
    ):
        subprocess.run(["git", *args], cwd=path, check=True, capture_output=True, text=True)


def _git(path: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=path, check=True, capture_output=True, text=True)


def test_collect_changes_reports_modified_and_untracked(tmp_path: Path) -> None:
    """Characterization: plain modify/add/delete map to clean paths today."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "keep.txt").write_text("v1\n", encoding="utf-8")
    (repo / "remove.txt").write_text("bye\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "init")

    (repo / "keep.txt").write_text("v2\n", encoding="utf-8")
    (repo / "remove.txt").unlink()
    (repo / "new.txt").write_text("hello\n", encoding="utf-8")

    service = GitWorktreeService(base_dir=tmp_path / "wt")
    changes = service.collect_changes(repo)

    assert set(changes) == {"keep.txt", "remove.txt", "new.txt"}


@pytest.mark.xfail(
    reason="BUG: collect_changes parses `R old -> new` as one literal path "
    "instead of returning the new (and/or old) file path",
    strict=False,
)
def test_collect_changes_reports_new_path_for_staged_rename(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "a.txt").write_text("content that is long enough to be detected\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "init")
    _git(repo, "mv", "a.txt", "b.txt")

    service = GitWorktreeService(base_dir=tmp_path / "wt")
    changes = service.collect_changes(repo)

    # The renamed destination must be reported as a real, usable path.
    assert "b.txt" in changes
    # And no entry should still carry git's "old -> new" rename arrow.
    assert all("->" not in entry for entry in changes)


def test_collect_changes_current_behavior_on_rename_keeps_arrow(tmp_path: Path) -> None:
    """Characterization of the bug: documents the broken output exactly."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "a.txt").write_text("content that is long enough to be detected\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "init")
    _git(repo, "mv", "a.txt", "b.txt")

    service = GitWorktreeService(base_dir=tmp_path / "wt")
    changes = service.collect_changes(repo)

    # Today the single entry is the raw arrow string, not a path git can act on.
    assert changes == ["a.txt -> b.txt"]
