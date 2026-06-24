from __future__ import annotations

from app.admin.advanced_settings import FileAdvancedSettingsStore

_DEFAULT_JOB_TIMEOUT_SECONDS = 1800
_DEFAULT_GIT_REMOTE_NAME = "origin"
_DEFAULT_KEEP_WORKTREE_ON_SUCCESS = True


class EffectiveConfig:
    """Resolves runtime settings from the advanced-settings store, falling back to
    built-in defaults when no store is configured."""

    def __init__(self, advanced_settings_store: FileAdvancedSettingsStore | None) -> None:
        self._advanced_settings_store = advanced_settings_store

    def job_timeout_seconds(self) -> int:
        if self._advanced_settings_store is None:
            return _DEFAULT_JOB_TIMEOUT_SECONDS
        return self._advanced_settings_store.get().job_timeout_seconds

    def git_remote_name(self) -> str:
        if self._advanced_settings_store is None:
            return _DEFAULT_GIT_REMOTE_NAME
        return self._advanced_settings_store.get().git_remote_name

    def keep_worktree_on_success(self) -> bool:
        if self._advanced_settings_store is None:
            return _DEFAULT_KEEP_WORKTREE_ON_SUCCESS
        return self._advanced_settings_store.get().keep_worktree_on_success
