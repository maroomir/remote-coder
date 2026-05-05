from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


_CODE_SUFFIXES: frozenset[str] = frozenset(
    {
        ".py",
        ".pyi",
        ".pyx",
        ".md",
        ".toml",
        ".yaml",
        ".yml",
        ".json",
        ".rs",
        ".go",
        ".c",
        ".h",
        ".cpp",
        ".hpp",
        ".java",
        ".kt",
        ".swift",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".mjs",
        ".cjs",
        ".css",
        ".scss",
        ".html",
        ".htm",
        ".vue",
        ".svelte",
        ".sql",
        ".sh",
        ".bash",
        ".zsh",
        ".dockerfile",
    }
)

_SKIP_DIR_NAMES: frozenset[str] = frozenset(
    {
        ".git",
        ".remote-coder",
        "__pycache__",
        ".venv",
        "venv",
        ".tox",
        "node_modules",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".idea",
        ".vscode",
        "dist",
        "build",
        ".eggs",
    }
)


@dataclass(frozen=True)
class ProjectCodeStats:
    files_scanned: int
    total_lines: int
    skipped_binary_or_error: int


def count_project_code(
    project_root: Path,
    *,
    worktree_base_dir: Path | None = None,
    max_files: int = 50_000,
) -> ProjectCodeStats:
    root = project_root.resolve()
    wt_base = worktree_base_dir.resolve() if worktree_base_dir is not None else None

    files_scanned = 0
    total_lines = 0
    skipped = 0

    for path in root.rglob("*"):
        if files_scanned >= max_files:
            break
        if not path.is_file():
            continue
        try:
            rel = path.relative_to(root)
        except ValueError:
            continue
        if _should_skip_relative(rel, root, wt_base):
            continue

        suf = path.suffix.lower()
        if suf == "" and path.name in {"Dockerfile", "Makefile", "Justfile"}:
            pass
        elif suf not in _CODE_SUFFIXES:
            continue

        try:
            data = path.read_bytes()
        except OSError:
            skipped += 1
            continue
        if b"\x00" in data[:8192]:
            skipped += 1
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text = data.decode("utf-8", errors="replace")
            except OSError:
                skipped += 1
                continue

        line_count = 1 + text.count("\n") if text else 0
        total_lines += line_count
        files_scanned += 1

    return ProjectCodeStats(
        files_scanned=files_scanned,
        total_lines=total_lines,
        skipped_binary_or_error=skipped,
    )


def format_code_monitor(stats: ProjectCodeStats, project_name: str, root: Path) -> str:
    return "\n".join(
        [
            "코드 규모(추정)",
            f"프로젝트: {project_name}",
            f"root: {root}",
            f"스캔한 코드 파일 수: {stats.files_scanned}",
            f"합계 줄 수(대략): {stats.total_lines}",
            f"건너뜀(바이너리/읽기 오류): {stats.skipped_binary_or_error}",
            "",
            "참고: 확장자 기준 텍스트 파일만 포함합니다. 대용량 저장소에서는 상한에 도달하면 일부만 집계됩니다.",
        ]
    )


def _should_skip_relative(rel: Path, root: Path, wt_base: Path | None) -> bool:
    for p in rel.parts[:-1]:
        if p in _SKIP_DIR_NAMES:
            return True
        if p.endswith(".egg-info"):
            return True
    if wt_base is None:
        return False
    try:
        candidate = (root / rel).resolve()
        candidate.relative_to(wt_base)
        return True
    except ValueError:
        return False
