from pathlib import Path

import pytest

from app.config import Settings
from app.projects.registry import ProjectRegistry


@pytest.fixture
def test_settings(tmp_path: Path) -> Settings:
    return Settings(
        telegram_bot_token="token",
        telegram_allowed_chat_ids=[123],
        telegram_allowed_user_ids=[],
        default_model="claude",
        default_project="remote-coder",
        project_root=tmp_path,
        worktree_base_dir=tmp_path / "worktrees",
        job_timeout_seconds=10,
        keep_worktree_on_success=True,
    )


@pytest.fixture
def project_registry(test_settings: Settings) -> ProjectRegistry:
    path = test_settings.project_root / "test-projects-registry.json"
    reg = ProjectRegistry(path)
    reg.ensure_seeded_from_settings(test_settings)
    return reg
