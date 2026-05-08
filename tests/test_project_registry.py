from pathlib import Path

import pytest
from pydantic import SecretStr

from app.config import Settings
from app.models import ModelName
from app.projects.registry import (
    ProjectRecord,
    ProjectRegistry,
    build_public_webhook_url,
    compute_token_hash,
    compute_token_hash_prefix,
    mask_bot_token,
    projects_config_path_for_settings,
)


def test_projects_config_path_explicit(tmp_path: Path) -> None:
    explicit = tmp_path / "custom" / "p.json"
    resolved = projects_config_path_for_settings(tmp_path, explicit)
    assert resolved == explicit.resolve()


def test_projects_config_path_default_under_project_root(tmp_path: Path) -> None:
    resolved = projects_config_path_for_settings(tmp_path, None)
    assert resolved == (tmp_path / ".remote-coder" / "projects.json").resolve()


def test_ensure_seeded_empty_file_with_token_writes_seed(tmp_path: Path) -> None:
    path = tmp_path / ".remote-coder" / "projects.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"default_project": "", "projects": []}\n', encoding="utf-8")
    root = tmp_path / "repo"
    root.mkdir()
    wt = tmp_path / "wt"
    wt.mkdir()
    settings = Settings(
        telegram_bot_token="seed-token",
        telegram_allowed_chat_ids=[42],
        telegram_allowed_user_ids=[7],
        telegram_webhook_secret="whsec",
        default_project="seed-proj",
        default_model="claude",
        project_root=root,
        worktree_base_dir=wt,
    )
    reg = ProjectRegistry(path)
    reg.ensure_seeded_from_settings(settings)
    reg.load()
    assert reg.get_default_project_name() == "seed-proj"
    proj = reg.get("seed-proj")
    assert proj is not None
    assert proj.bot_token.get_secret_value() == "seed-token"
    assert proj.webhook_secret is not None
    assert proj.webhook_secret.get_secret_value() == "whsec"
    assert proj.allowed_chat_ids == [42]
    assert proj.allowed_user_ids == [7]


def test_ensure_seeded_without_token_writes_empty_projects(tmp_path: Path) -> None:
    path = tmp_path / ".remote-coder" / "projects.json"
    root = tmp_path / "repo"
    root.mkdir()
    wt = tmp_path / "wt"
    wt.mkdir()
    settings = Settings(
        telegram_bot_token=None,
        default_project="p1",
        default_model="claude",
        project_root=root,
        worktree_base_dir=wt,
    )
    reg = ProjectRegistry(path)
    assert not path.exists()
    reg.ensure_seeded_from_settings(settings)
    assert path.exists()
    reg.load()
    assert reg.list_projects() == []


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
                bot_token="another-token",
                allowed_chat_ids=[123],
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
                bot_token="newproj-token",
                allowed_chat_ids=[123],
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


def test_compute_token_hash_returns_sha256_hex() -> None:
    token_hash = compute_token_hash("abc")
    assert token_hash == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_to_public_dict_masks_bot_token_and_omits_secrets(test_settings: Settings) -> None:
    path = test_settings.project_root / "pub.json"
    reg = ProjectRegistry(path)
    reg.ensure_seeded_from_settings(test_settings)
    public = reg.to_public_dict()
    proj = next(p for p in public["projects"] if p["name"] == "remote-coder")
    token_plain = reg.get("remote-coder")
    assert token_plain is not None
    assert proj["bot_token_masked"] == mask_bot_token(token_plain.bot_token.get_secret_value())
    prefix = compute_token_hash_prefix(token_plain.bot_token.get_secret_value())
    assert proj["webhook_path"] == f"/telegram/webhook/{prefix}"
    assert proj["token_hash_prefix"] == prefix
    assert "bot_token" not in proj
    assert "webhook_secret" not in proj


def test_get_by_token_hash_exact_prefix_match(test_settings: Settings) -> None:
    path = test_settings.project_root / "hash.json"
    reg = ProjectRegistry(path)
    reg.ensure_seeded_from_settings(test_settings)

    project = reg.get("remote-coder")
    assert project is not None
    token_hash_prefix = compute_token_hash_prefix(project.bot_token.get_secret_value())

    matched = reg.get_by_token_hash(token_hash_prefix)
    assert matched is not None
    assert matched.name == "remote-coder"


def test_get_by_token_hash_rejects_non_normalized_segment(test_settings: Settings) -> None:
    path = test_settings.project_root / "hashnorm.json"
    reg = ProjectRegistry(path)
    reg.ensure_seeded_from_settings(test_settings)
    project = reg.get("remote-coder")
    assert project is not None
    full = compute_token_hash(project.bot_token.get_secret_value())
    assert reg.get_by_token_hash(full) is None
    assert reg.get_by_token_hash(full[:15]) is None


def test_add_project_rejects_webhook_prefix_collision(test_settings: Settings) -> None:
    path = test_settings.project_root / "coll_add.json"
    reg = ProjectRegistry(path)
    reg.ensure_seeded_from_settings(test_settings)
    existing = reg.get("remote-coder")
    assert existing is not None
    root2 = test_settings.project_root / "repo2"
    root2.mkdir()
    wt2 = test_settings.worktree_base_dir / "wt2"
    wt2.mkdir(parents=True)

    with pytest.raises(ValueError, match="prefix collision"):
        reg.add_project(
            ProjectRecord(
                name="other",
                root_path=root2,
                worktree_base_dir=wt2,
                default_model=ModelName.CLAUDE,
                enabled=True,
                bot_token=SecretStr(existing.bot_token.get_secret_value()),
                allowed_chat_ids=[123],
            )
        )


def test_update_project_rejects_webhook_prefix_collision(test_settings: Settings) -> None:
    path = test_settings.project_root / "coll_upd.json"
    reg = ProjectRegistry(path)
    reg.ensure_seeded_from_settings(test_settings)
    root_a = test_settings.project_root / "repo_a"
    root_a.mkdir()
    root_b = test_settings.project_root / "repo_b"
    root_b.mkdir()
    wt_a = test_settings.worktree_base_dir / "wta"
    wt_a.mkdir(parents=True)
    wt_b = test_settings.worktree_base_dir / "wtb"
    wt_b.mkdir(parents=True)

    reg.add_project(
        ProjectRecord(
            name="proj-a",
            root_path=root_a,
            worktree_base_dir=wt_a,
            default_model=ModelName.CLAUDE,
            enabled=True,
            bot_token=SecretStr("token-a-only"),
            allowed_chat_ids=[1],
        )
    )
    reg.add_project(
        ProjectRecord(
            name="proj-b",
            root_path=root_b,
            worktree_base_dir=wt_b,
            default_model=ModelName.CLAUDE,
            enabled=True,
            bot_token=SecretStr("token-b-only"),
            allowed_chat_ids=[1],
        )
    )
    proj_a = reg.get("proj-a")
    assert proj_a is not None
    with pytest.raises(ValueError, match="prefix collision"):
        reg.update_project(
            "proj-b",
            ProjectRecord(
                name="proj-b",
                root_path=root_b,
                worktree_base_dir=wt_b,
                default_model=ModelName.CLAUDE,
                enabled=True,
                bot_token=SecretStr(proj_a.bot_token.get_secret_value()),
                allowed_chat_ids=[1],
            ),
        )


def test_build_public_webhook_url_matches_registry_webhook_path(project_registry: ProjectRegistry) -> None:
    entry = project_registry.get("remote-coder")
    assert entry is not None
    token = entry.bot_token.get_secret_value()
    public = project_registry.to_public_dict()
    row = next(p for p in public["projects"] if p["name"] == "remote-coder")
    assert build_public_webhook_url("https://example.com", token) == "https://example.com" + row["webhook_path"]
    assert build_public_webhook_url("https://example.com/", token) == "https://example.com" + row["webhook_path"]
