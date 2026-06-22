"""Regression + characterization tests for app.git.service.collect_changes.

Tester 3 (AI Runners & Git Automation). These probe how the changed-files list
that flows into F6 (commit message scope, result notification "수정 파일 목록",
and the stored job result) is built from `git status --porcelain`.

FIXED: a staged rename emits a single porcelain line `R  old -> new`. The old
`line[3:].strip()` stored the literal string `old -> new` as one file path,
corrupting changed_files reporting and commit scope inference. `collect_changes`
now parses `git status --porcelain -z` and keeps the unquoted destination path;
these tests guard against a regression.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

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


def test_collect_changes_reports_new_path_for_staged_rename(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "a.txt").write_text("content that is long enough to be detected\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "init")
    _git(repo, "mv", "a.txt", "b.txt")

    service = GitWorktreeService(base_dir=tmp_path / "wt")
    changes = service.collect_changes(repo)

    # The renamed destination is reported as a real, usable path with no arrow.
    assert changes == ["b.txt"]
    assert all("->" not in entry for entry in changes)


def test_collect_changes_handles_renamed_path_with_spaces(tmp_path: Path) -> None:
    """A rename whose destination contains spaces must stay a single clean path."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "a.txt").write_text("content that is long enough to be detected\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "init")
    _git(repo, "mv", "a.txt", "b with space.txt")

    service = GitWorktreeService(base_dir=tmp_path / "wt")
    changes = service.collect_changes(repo)

    # `-z` parsing keeps the unquoted destination; the origin field is dropped.
    assert changes == ["b with space.txt"]


def test_collect_diff_numstat_counts_modified_and_new_files(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "keep.txt").write_text("a\nb\nc\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "init")

    (repo / "keep.txt").write_text("a\nB\nc\nd\n", encoding="utf-8")
    (repo / "new.txt").write_text("x\ny\n", encoding="utf-8")

    service = GitWorktreeService(base_dir=tmp_path / "wt")
    stats = dict((path, (added, deleted)) for path, added, deleted in service.collect_diff_numstat(repo))

    # Untracked new.txt is surfaced via intent-to-add with its real line counts.
    assert stats["new.txt"] == (2, 0)
    # keep.txt added one line ("d") and changed one ("b" -> "B"): +2 / -1.
    assert stats["keep.txt"] == (2, 1)


def test_collect_diff_numstat_marks_binary_as_none(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "init")

    (repo / "logo.png").write_bytes(b"\x00\x01\x02\x00\xff")

    service = GitWorktreeService(base_dir=tmp_path / "wt")
    stats = dict((path, (added, deleted)) for path, added, deleted in service.collect_diff_numstat(repo))

    assert stats["logo.png"] == (None, None)


def test_collect_diff_numstat_keeps_destination_for_rename(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "a.txt").write_text("content that is long enough to be detected\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "init")
    _git(repo, "mv", "a.txt", "b.txt")

    service = GitWorktreeService(base_dir=tmp_path / "wt")
    paths = [path for path, _, _ in service.collect_diff_numstat(repo)]

    assert "b.txt" in paths
    assert all("\t" not in path and "=>" not in path for path in paths)
