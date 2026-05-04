from __future__ import annotations

import re


class CommitMessageFormatter:
    """Remote AI Coder 작업용 Git 커밋 메시지 포맷터."""

    _OPTION_PATTERN = re.compile(
        r"\b(?:model|branch|project)\s*:\s*\S+|\bno\s+commit\b",
        flags=re.IGNORECASE,
    )
    _SPEAKER_PREFIX_PATTERN = re.compile(r"^(?:user|사용자)\s*:\s*", flags=re.IGNORECASE)
    _PARENTHETICAL_EXAMPLE_PATTERN = re.compile(r"\((?:ex|예시?)>?.*?\)", flags=re.IGNORECASE)
    _WHITESPACE_PATTERN = re.compile(r"\s+")
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

    @classmethod
    def format(
        cls,
        job_id: str,
        instruction: str,
        changed_files: list[str],
        ai_body: str | None = None,
        ai_title: str | None = None,
    ) -> str:
        commit_type = cls._infer_type(instruction, changed_files)
        title = ai_title if ai_title else cls._build_title(instruction, changed_files)
        if ai_body:
            body = ai_body
        else:
            bullets = cls._build_bullets(commit_type, changed_files)
            body = "\n".join(f"- {bullet}" for bullet in bullets)
        return f"{commit_type}: {title}\n\n{body}\n\ncommitted by remote-coder: {job_id}"

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
    def _build_title(cls, instruction: str, changed_files: list[str]) -> str:
        summary = cls._instruction_summary(instruction)
        if summary:
            return summary

        if any(path.startswith("app/monitoring/") for path in changed_files):
            return "update monitoring behavior"
        if any(path.startswith("app/telegram/") for path in changed_files):
            return "update telegram behavior"
        if any(path.startswith("app/admin/") for path in changed_files):
            return "update admin behavior"
        if any(path.startswith("app/git/") for path in changed_files):
            return "update git workflow"
        if any(path.startswith("docs/") or path == "README.md" for path in changed_files):
            return "update project documentation"
        return "update requested behavior"

    @classmethod
    def _instruction_summary(cls, instruction: str, max_length: int = 72) -> str:
        line = cls._first_meaningful_instruction_line(instruction)
        if not line:
            return ""

        line = cls._SPEAKER_PREFIX_PATTERN.sub("", line)
        line = cls._OPTION_PATTERN.sub("", line)
        line = cls._PARENTHETICAL_EXAMPLE_PATTERN.sub("", line)
        line = cls._WHITESPACE_PATTERN.sub(" ", line).strip()
        line = line.strip().strip("-:;,.!?").strip("\"'`")
        if not line:
            return ""

        if cls._mentions_monitor_model_metrics(line):
            return "show current model and token usage in monitor model"
        return cls._truncate_at_word(cls._lowercase_initial_ascii(line), max_length)

    @staticmethod
    def _first_meaningful_instruction_line(instruction: str) -> str:
        for raw_line in instruction.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("[") and line.endswith("]"):
                continue
            if line.startswith("message_id="):
                continue
            if line.startswith("Job 결과:"):
                continue
            return line
        return ""

    @staticmethod
    def _mentions_monitor_model_metrics(text: str) -> bool:
        lowered = text.casefold()
        return "monitor model" in lowered and ("토큰" in lowered or "token" in lowered)

    @staticmethod
    def _truncate_at_word(text: str, max_length: int) -> str:
        if len(text) <= max_length:
            return text
        clipped = text[: max_length + 1].rsplit(" ", 1)[0].strip()
        if not clipped:
            clipped = text[:max_length].strip()
        return clipped.rstrip(".,;:")

    @staticmethod
    def _lowercase_initial_ascii(text: str) -> str:
        if len(text) >= 2 and "A" <= text[0] <= "Z" and not ("A" <= text[1] <= "Z"):
            return text[0].lower() + text[1:]
        return text

    @classmethod
    def _build_bullets(cls, commit_type: str, changed_files: list[str]) -> list[str]:
        first_bullets = {
            "fix": "AI agent fixed the requested behavior",
            "refactor": "AI agent refactored the requested area",
            "chore": "AI agent maintained project assets",
            "feat": "AI agent implemented the requested change",
        }
        bullets: list[str] = [first_bullets.get(commit_type, "AI agent implemented the requested change")]

        if any(path.startswith("tests/") for path in changed_files):
            bullets.append("AI agent updated automated coverage where applicable")
        elif any(cls._is_doc_path(path) for path in changed_files):
            bullets.append("AI agent refreshed related documentation where applicable")
        return bullets[:2]

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
