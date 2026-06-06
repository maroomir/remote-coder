from __future__ import annotations

import re


class CommitMessageFormatter:
    _OPTION_PATTERN = re.compile(
        r"\b(?:model|branch|project)\s*:\s*\S+|\bno\s+commit\b",
        flags=re.IGNORECASE,
    )
    _SPEAKER_PREFIX_PATTERN = re.compile(r"^user\s*:\s*", flags=re.IGNORECASE)
    _PARENTHETICAL_EXAMPLE_PATTERN = re.compile(r"\(ex>?.*?\)", flags=re.IGNORECASE)
    _WHITESPACE_PATTERN = re.compile(r"\s+")
    _REQUEST_MARKERS = (
        "please",
        "can you",
        "could you",
        "would you",
    )
    _FIX_KEYWORDS = (
        "bug",
        "error",
        "fix",
        "issue",
        "patch",
        "repair",
        "resolve",
    )
    _REFACTOR_KEYWORDS = (
        "cleanup",
        "extract",
        "refactor",
        "rename",
        "restructure",
        "simplify",
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
        title = cls._safe_ai_title(ai_title) or cls._build_title(
            instruction,
            changed_files,
            commit_type,
        )
        body = cls._safe_ai_body(ai_body)
        if body is None:
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
    def _build_title(cls, instruction: str, changed_files: list[str], commit_type: str) -> str:
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
        scoped_title = cls._build_scoped_title(commit_type, changed_files)
        if scoped_title:
            return scoped_title
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
        if not cls._is_ascii_text(line):
            return ""

        if cls._mentions_monitor_model_metrics(line):
            return "show current model and token usage in monitor model"
        if cls._looks_like_raw_request(line):
            return ""
        return cls._truncate_at_word(cls._lowercase_initial_ascii(line), max_length)

    @classmethod
    def _safe_ai_title(
        cls,
        ai_title: str | None,
        max_length: int = 72,
    ) -> str | None:
        if ai_title is None:
            return None
        title = cls._WHITESPACE_PATTERN.sub(" ", ai_title).strip()
        title = title.strip().strip("-:;,.!?").strip("\"'`")
        if not title or len(title) > max_length:
            return None
        if not cls._is_ascii_text(title):
            return None
        if cls._looks_like_raw_request(title):
            return None
        return cls._lowercase_initial_ascii(title)

    @classmethod
    def _safe_ai_body(cls, ai_body: str | None) -> str | None:
        if ai_body is None:
            return None
        lines = [line.rstrip() for line in ai_body.strip().splitlines() if line.strip()]
        if not lines:
            return None
        body = "\n".join(lines)
        if not cls._is_ascii_text(body):
            return None
        return body

    @classmethod
    def _looks_like_raw_request(cls, text: str) -> bool:
        lowered = text.casefold()
        return any(marker in lowered for marker in cls._REQUEST_MARKERS)

    @classmethod
    def _build_scoped_title(cls, commit_type: str, changed_files: list[str]) -> str:
        scope = cls._common_source_scope(changed_files)
        if not scope:
            return ""
        verb = {
            "fix": "fix",
            "refactor": "refactor",
            "chore": "maintain",
        }.get(commit_type, "update")
        return f"{verb} {scope}"

    @staticmethod
    def _common_source_scope(changed_files: list[str]) -> str:
        source_files = [
            path
            for path in changed_files
            if "/" in path and not path.startswith(("tests/", "docs/", "."))
        ]
        if not source_files:
            return ""

        split_paths = [path.split("/")[:-1] for path in source_files]
        common: list[str] = []
        for parts in zip(*split_paths):
            if len(set(parts)) != 1:
                break
            common.append(parts[0])
        if common:
            return f"{'/'.join(common)} source"
        return f"{source_files[0].split('/', 1)[0]} source"

    _CURRENT_REQUEST_MARKERS = (
        "[Current request]",
        "[/current request]",
    )
    _CONTEXT_NOISE_PREFIXES = (
        "job_id=",
        "message_id=",
    )

    @classmethod
    def _first_meaningful_instruction_line(cls, instruction: str) -> str:
        skip_depth = 0
        for raw_line in instruction.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line in cls._CURRENT_REQUEST_MARKERS:
                continue
            if line.startswith("[/") and line.endswith("]"):
                skip_depth = max(0, skip_depth - 1)
                continue
            if line.startswith("[") and line.endswith("]"):
                skip_depth += 1
                continue
            if skip_depth > 0:
                continue
            if any(line.startswith(prefix) for prefix in cls._CONTEXT_NOISE_PREFIXES):
                continue
            return line
        return ""

    @staticmethod
    def _mentions_monitor_model_metrics(text: str) -> bool:
        lowered = text.casefold()
        return "monitor model" in lowered and "token" in lowered

    @staticmethod
    def _is_ascii_text(text: str) -> bool:
        return text.isascii()

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
