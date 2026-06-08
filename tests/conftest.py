from pathlib import Path

import pytest
from pydantic import SecretStr

from app.admin.advanced_settings import FileAdvancedSettingsStore, advanced_settings_path
from app.config import Settings
from app.monitoring.log_buffer import InMemoryLogBuffer
from app.models import ModelName
from app.projects.registry import ProjectRecord, ProjectRegistry
from app.telegram.conversation import SQLiteConversationStore


@pytest.fixture(autouse=True)
def isolate_remote_coder_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "remote-coder-home"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("REMOTE_CODER_HOME", str(home))
    return home


@pytest.fixture
def test_settings() -> Settings:
    return Settings()


@pytest.fixture
def project_registry(isolate_remote_coder_home: Path, tmp_path: Path) -> ProjectRegistry:
    path = isolate_remote_coder_home / "test-projects-registry.json"
    reg = ProjectRegistry(path)
    root = tmp_path / "repo"
    root.mkdir(parents=True, exist_ok=True)
    reg.add_project(
        ProjectRecord(
            name="remote-coder",
            root_path=root,
            default_model=ModelName.CLAUDE,
            enabled=True,
            bot_token=SecretStr("token"),
            allowed_chat_ids=[123],
            allowed_user_ids=[],
        )
    )
    return reg


@pytest.fixture
def advanced_settings_store(isolate_remote_coder_home: Path) -> FileAdvancedSettingsStore:
    store = FileAdvancedSettingsStore(advanced_settings_path())
    store.load()
    return store


@pytest.fixture
def log_buffer() -> InMemoryLogBuffer:
    return InMemoryLogBuffer(max_entries=500)


@pytest.fixture
def conversation_store(isolate_remote_coder_home: Path) -> SQLiteConversationStore:
    path = isolate_remote_coder_home / "admin_test_conversations.sqlite3"
    return SQLiteConversationStore(path)
