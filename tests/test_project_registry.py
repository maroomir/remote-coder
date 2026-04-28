from pathlib import Path

import pytest

from app.config import Settings
from app.models import ModelName
from app.projects.registry import ProjectRecord, ProjectRegistry, projects_config_path_for_settings


def test_projects_config_path_explicit(tmp_path: Path) -> None:
    explicit = tmp_path / "custom" / "p.json"
    resolved = projects_config_path_for_settings(tmp_path, explicit)
    assert resolved == explicit.resolve()


def test_projects_config_path_default_under_project_root(tmp_path: Path) -> None:
    resolved = projects_config_path_for_settings(tmp_path, None)
    assert resolved == (tmp_path / ".remote-coder" / "projects.json").resolve()


def test_ensure_seeded_creates_file(test_settings: Settings) -> None:
    path = test_settings.project_root / "seed.json"
    reg = ProjectRegistry(path)
    assert not path.exists()
    reg.ensure_seeded_from_settings(test_settings)
    assert path.exists()
    reg.load()
    assert reg.get_default_project_name() == "remote-coder"
    assert reg.get("remote-coder") is not None


def test_add_duplicate_project_raises(test_settings: Settings) -> None:
    path = test_settings.project_root / "dup.json"
    reg = ProjectRegistry(path)
    reg.ensure_seeded_from_settings(test_settings)
    with pytest.raises(ValueError, match="already exists"):
        reg.add_project(
            ProjectRecord(
                name="remote-coder",
                root_path=test_settings.project_root,
                worktree_base_dir=test_settings.worktree_base_dir,
                default_model=ModelName.CLAUDE,
                enabled=True,
            )
        )


def test_add_project_invalid_root_raises(test_settings: Settings) -> None:
    path = test_settings.project_root / "inv.json"
    reg = ProjectRegistry(path)
    reg.ensure_seeded_from_settings(test_settings)
    missing = test_settings.project_root / "does_not_exist"
    with pytest.raises(ValueError, match="does not exist"):
        reg.add_project(
            ProjectRecord(
                name="newproj",
                root_path=missing,
                worktree_base_dir=test_settings.worktree_base_dir,
                default_model=ModelName.CLAUDE,
                enabled=True,
            )
        )


def test_yaml_config_roundtrip(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    wt = tmp_path / "wt"
    wt.mkdir()
    path = tmp_path / "cfg.yaml"
    settings = Settings(
        telegram_bot_token="t",
        telegram_allowed_chat_ids=[1],
        default_project="p1",
        default_model="claude",
        project_root=root,
        worktree_base_dir=wt,
    )
    reg = ProjectRegistry(path)
    reg.ensure_seeded_from_settings(settings)
    reg2 = ProjectRegistry(path)
    reg2.load()
    assert reg2.get_default_project_name() == "p1"
    assert reg2.get("p1") is not None
