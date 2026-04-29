from enum import StrEnum


class ModelName(StrEnum):
    CLAUDE = "claude"
    CODEX = "codex"


class CodexSandboxMode(StrEnum):
    """Codex CLI `--sandbox` 값과 동일. `codex exec` 기본은 read-only이므로 Remote AI Coder는 기본을 workspace-write로 둡니다."""

    READ_ONLY = "read-only"
    WORKSPACE_WRITE = "workspace-write"
    DANGER_FULL_ACCESS = "danger-full-access"
