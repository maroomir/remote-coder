from pathlib import Path

import pytest

from app.admin.advanced_settings import FileAdvancedSettingsStore, advanced_settings_path_for_project_root
from app.config import Settings
from app.monitoring.log_buffer import InMemoryLogBuffer
from app.projects.registry import ProjectRegistry
from app.telegram.conversation import SQLiteConversationStore


@pytest.fixture(autouse=True)
def isolate_remote_coder_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    # ProjectRecord/Settings derive worktree + state paths from remote_coder_home();
    # pin it to a tmp dir so tests never touch the real ~/.remote-coder.
    home = tmp_path / "remote-coder-home"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("REMOTE_CODER_HOME", str(home))
    return home


@pytest.fixture
def test_settings(tmp_path: Path) -> Settings:
    return Settings(
        telegram_bot_token="token",
        telegram_allowed_chat_ids=[123],
        telegram_allowed_user_ids=[],
        telegram_webhook_secret=None,
        default_model="claude",
        default_project="remote-coder",
        project_root=tmp_path,
        job_timeout_seconds=10,
        keep_worktree_on_success=True,
    )


@pytest.fixture
def project_registry(test_settings: Settings) -> ProjectRegistry:
    path = test_settings.project_root / "test-projects-registry.json"
    reg = ProjectRegistry(path)
    reg.ensure_seeded_from_settings(test_settings)
    return reg


@pytest.fixture
def advanced_settings_store(test_settings: Settings) -> FileAdvancedSettingsStore:
    path = advanced_settings_path_for_project_root(test_settings.project_root)
    store = FileAdvancedSettingsStore(path)
    store.load()
    return store


@pytest.fixture
def log_buffer() -> InMemoryLogBuffer:
    return InMemoryLogBuffer(max_entries=500)


@pytest.fixture
def conversation_store(test_settings: Settings) -> SQLiteConversationStore:
    path = test_settings.project_root / ".remote-coder" / "admin_test_conversations.sqlite3"
    return SQLiteConversationStore(path)
