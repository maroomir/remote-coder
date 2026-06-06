from enum import StrEnum


class UiLanguage(StrEnum):
    ENGLISH = "en"
    KOREAN = "ko"


class ModelName(StrEnum):
    CLAUDE = "claude"
    CODEX = "codex"
    GEMINI = "gemini"


class CodexSandboxMode(StrEnum):
    """Matches Codex CLI `--sandbox`; remote-coder defaults to workspace-write."""

    READ_ONLY = "read-only"
    WORKSPACE_WRITE = "workspace-write"
    DANGER_FULL_ACCESS = "danger-full-access"
