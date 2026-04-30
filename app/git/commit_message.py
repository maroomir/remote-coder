from __future__ import annotations

import re
from pathlib import Path


class CommitMessageFormatter:
    """Remote AI Coder 작업용 Git 커밋 메시지 포맷터."""

    _WORD_BREAK_PATTERN = re.compile(r"[_-]+")
    _FIX_KEYWORDS = (
        "bug",
        "error",
        "fix",
        "issue",
        "patch",
        "repair",
        "resolve",
        "고치",
        "버그",
        "수정",
        "오류",
    )
    _REFACTOR_KEYWORDS = (
        "cleanup",
        "extract",
        "refactor",
        "rename",
        "restructure",
        "simplify",
        "개선",
        "리팩터링",
        "정리",
    )
    _CHORE_KEYWORDS = (
        "build",
        "chore",
        "ci",
        "config",
        "dependency",
        "deps",
        "docs",
        "documentation",
        "readme",
        "test",
        "문서",
        "설정",
        "의존성",
        "테스트",
    )
    _AREA_LABELS = {
        "admin": "admin",
        "ai": "AI",
        "git": "git",
        "jobs": "job",
        "projects": "project",
        "security": "security",
        "telegram": "telegram",
        "tests": "test",
    }

    @classmethod
    def format(cls, job_id: str, instruction: str, changed_files: list[str]) -> str:
        commit_type = cls._infer_type(instruction, changed_files)
        title = cls._build_title(changed_files)
        bullets = cls._build_bullets(changed_files)
        body = "\n".join(f"- {bullet}" for bullet in bullets)
        return f"{commit_type}: {title}\n{body}\n\ncommitted by remote-coder:{job_id}"

    @classmethod
    def _infer_type(cls, instruction: str, changed_files: list[str]) -> str:
        lowered = instruction.casefold()
        if any(keyword in lowered for keyword in cls._FIX_KEYWORDS):
            return "fix"
        if changed_files and all(cls._is_chore_path(path) for path in changed_files):
            return "chore"
        if any(keyword in lowered for keyword in cls._REFACTOR_KEYWORDS):
            return "refactor"
        if any(keyword in lowered for keyword in cls._CHORE_KEYWORDS):
            return "chore"
        return "feat"

    @classmethod
    def _build_title(cls, changed_files: list[str]) -> str:
        primary_paths = [path for path in changed_files if not cls._is_supporting_path(path)] or changed_files
        scope = cls._join_labels(cls._describe_paths(primary_paths, limit=2))
        if not scope:
            return "update requested changes"
        return f"update {scope}"

    @classmethod
    def _build_bullets(cls, changed_files: list[str]) -> list[str]:
        bullets: list[str] = []
        scope = cls._join_labels(cls._describe_paths(changed_files, limit=3))
        if scope:
            bullets.append(f"update {scope}")
        else:
            bullets.append("apply the requested file changes")

        if any(path.startswith("tests/") for path in changed_files):
            bullets.append("add or refresh automated coverage for the updated flow")
        elif any(cls._is_doc_path(path) for path in changed_files):
            bullets.append("refresh related documentation for the new behavior")
        elif len(changed_files) > 1:
            bullets.append(f"touch {len(changed_files)} files in this change set")
        return bullets[:2]

    @classmethod
    def _describe_paths(cls, paths: list[str], limit: int) -> list[str]:
        labels: list[str] = []
        for path in paths:
            label = cls._path_label(path)
            if label and label not in labels:
                labels.append(label)
            if len(labels) >= limit:
                break
        return labels

    @classmethod
    def _path_label(cls, path: str) -> str:
        path_obj = Path(path)
        if path == "README.md":
            return "README"
        if cls._is_doc_path(path):
            stem = cls._normalize_words(path_obj.stem)
            return f"{stem} documentation" if stem else "documentation"
        if path.startswith("tests/"):
            stem = path_obj.stem.removeprefix("test_")
            words = cls._normalize_words(stem)
            return f"{words} tests" if words else "tests"
        if path_obj.stem == "__init__":
            return cls._normalize_words(path_obj.parent.name)

        words = cls._normalize_words(path_obj.stem)
        if len(path_obj.parts) >= 3 and path_obj.parts[0] == "app":
            area = cls._AREA_LABELS.get(path_obj.parts[1], cls._normalize_words(path_obj.parts[1]))
            if words and words != area:
                return f"{area} {words}"
            return area
        return words or path_obj.name

    @classmethod
    def _join_labels(cls, labels: list[str]) -> str:
        if not labels:
            return ""
        if len(labels) == 1:
            return labels[0]
        if len(labels) == 2:
            return f"{labels[0]} and {labels[1]}"
        return f"{', '.join(labels[:-1])}, and {labels[-1]}"

    @classmethod
    def _normalize_words(cls, text: str) -> str:
        return " ".join(part for part in cls._WORD_BREAK_PATTERN.split(text.strip()) if part)

    @staticmethod
    def _is_doc_path(path: str) -> bool:
        return path == "README.md" or path.startswith("docs/")

    @classmethod
    def _is_chore_path(cls, path: str) -> bool:
        return (
            cls._is_doc_path(path)
            or path.startswith("tests/")
            or path.endswith(".yml")
            or path.endswith(".yaml")
            or path.endswith(".toml")
            or path.endswith(".ini")
            or path.endswith(".cfg")
        )

    @classmethod
    def _is_supporting_path(cls, path: str) -> bool:
        return path.startswith("tests/") or cls._is_doc_path(path)
