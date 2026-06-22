import json
import stat
from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from app.config import default_worktree_base_dir, remote_coder_home
from app.models import ModelName
from app.projects.registry import (
    ProjectRecord,
    ProjectRegistry,
    build_public_webhook_url,
    compute_token_hash,
    compute_token_hash_prefix,
    mask_bot_token,
    projects_config_path,
)
from app.projects.secret_store import SECRET_BACKEND_KEYRING, InMemorySecretStore


def _seed_registry(path: Path, root: Path, name: str = "remote-coder") -> ProjectRegistry:
    reg = ProjectRegistry(path)
    reg.add_project(
        ProjectRecord(
            name=name,
            root_path=root,
            default_model=ModelName.CLAUDE,
            enabled=True,
            bot_token=SecretStr("token"),
            allowed_chat_ids=[123],
            allowed_user_ids=[],
        )
    )
    return reg


def test_projects_config_path_explicit(tmp_path: Path) -> None:
    explicit = tmp_path / "custom" / "p.json"
    resolved = projects_config_path(explicit)
    assert resolved == explicit.resolve()


def test_projects_config_path_default_under_remote_coder_home() -> None:
    resolved = projects_config_path(None)
    assert resolved == (remote_coder_home() / "projects.json").resolve()


def test_ensure_empty_registry_file_creates_empty_payload(tmp_path: Path) -> None:
    path = tmp_path / "projects.json"
    reg = ProjectRegistry(path)
    reg.ensure_empty_registry_file()
    assert path.exists()
    reg.load()
    assert reg.list_projects() == []


def test_worktree_base_dir_is_derived_and_not_persisted(isolate_remote_coder_home: Path, tmp_path: Path) -> None:
    path = isolate_remote_coder_home / "wt-derive.json"
    root = tmp_path / "repo"
    root.mkdir(parents=True)
    reg = _seed_registry(path, root)

    entry = reg.get("remote-coder")
    assert entry is not None
    assert entry.worktree_base_dir == default_worktree_base_dir("remote-coder")

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert "worktree_base_dir" not in raw["projects"][0]


def test_test_command_persists_and_reloads(
    isolate_remote_coder_home: Path, tmp_path: Path
) -> None:
    path = isolate_remote_coder_home / "tc-roundtrip.json"
    root = tmp_path / "repo"
    root.mkdir(parents=True)
    reg = ProjectRegistry(path)
    reg.add_project(
        ProjectRecord(
            name="remote-coder",
            root_path=root,
            bot_token=SecretStr("token"),
            allowed_chat_ids=[123],
            test_command="pytest -q",
        )
    )

    reloaded = ProjectRegistry(path)
    reloaded.load()
    entry = reloaded.get("remote-coder")
    assert entry is not None
    assert entry.test_command == "pytest -q"


def test_registry_loads_legacy_file_without_test_command(
    isolate_remote_coder_home: Path, tmp_path: Path
) -> None:
    # Files written before the field existed must still load (backward compatible default None).
    path = isolate_remote_coder_home / "legacy.json"
    root = tmp_path / "repo"
    root.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "default_project": "remote-coder",
                "projects": [
                    {
                        "name": "remote-coder",
                        "root_path": str(root),
                        "bot_token": "token",
                        "allowed_chat_ids": [123],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    reg = ProjectRegistry(path)
    reg.load()
    entry = reg.get("remote-coder")
    assert entry is not None
    assert entry.test_command is None


def test_registry_file_is_written_with_owner_only_permissions(
    isolate_remote_coder_home: Path, tmp_path: Path
) -> None:
    # Plaintext bot tokens must never be world-readable (PLAN.md N1, SECURITY.md).
    path = isolate_remote_coder_home / "perms.json"
    root = tmp_path / "repo"
    root.mkdir(parents=True)
    _seed_registry(path, root)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_add_duplicate_project_raises(isolate_remote_coder_home: Path, tmp_path: Path) -> None:
    path = isolate_remote_coder_home / "dup.json"
    root = tmp_path / "repo"
    root.mkdir(parents=True)
    reg = _seed_registry(path, root)
    with pytest.raises(ValueError, match="already exists"):
        reg.add_project(
            ProjectRecord(
                name="remote-coder",
                root_path=root,
                default_model=ModelName.CLAUDE,
                enabled=True,
                bot_token=SecretStr("another-token"),
                allowed_chat_ids=[123],
            )
        )


def test_add_project_invalid_root_raises(isolate_remote_coder_home: Path, tmp_path: Path) -> None:
    path = isolate_remote_coder_home / "inv.json"
    root = tmp_path / "repo"
    root.mkdir(parents=True)
    reg = _seed_registry(path, root)
    missing = tmp_path / "does_not_exist"
    with pytest.raises(ValueError, match="does not exist"):
        reg.add_project(
            ProjectRecord(
                name="newproj",
                root_path=missing,
                default_model=ModelName.CLAUDE,
                enabled=True,
                bot_token=SecretStr("newproj-token"),
                allowed_chat_ids=[123],
            )
        )


def test_yaml_config_roundtrip(isolate_remote_coder_home: Path, tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir(parents=True)
    path = isolate_remote_coder_home / "cfg.yaml"
    reg = ProjectRegistry(path)
    reg.add_project(
        ProjectRecord(
            name="p1",
            root_path=root,
            default_model=ModelName.CLAUDE,
            enabled=True,
            bot_token=SecretStr("t"),
            allowed_chat_ids=[1],
        )
    )
    reg2 = ProjectRegistry(path)
    reg2.load()
    assert reg2.get_default_project_name() == "p1"
    assert reg2.get("p1") is not None


def test_compute_token_hash_returns_sha256_hex() -> None:
    token_hash = compute_token_hash("abc")
    assert token_hash == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_to_public_dict_masks_bot_token_and_omits_secrets(project_registry: ProjectRegistry) -> None:
    public = project_registry.to_public_dict()
    proj = next(p for p in public["projects"] if p["name"] == "remote-coder")
    token_plain = project_registry.get("remote-coder")
    assert token_plain is not None
    assert proj["bot_token_masked"] == mask_bot_token(token_plain.bot_token.get_secret_value())
    prefix = compute_token_hash_prefix(token_plain.bot_token.get_secret_value())
    assert proj["webhook_path"] == f"/telegram/webhook/{prefix}"
    assert proj["token_hash_prefix"] == prefix
    assert "bot_token" not in proj
    assert "webhook_secret" not in proj


def test_get_by_token_hash_exact_prefix_match(project_registry: ProjectRegistry) -> None:
    project = project_registry.get("remote-coder")
    assert project is not None
    token_hash_prefix = compute_token_hash_prefix(project.bot_token.get_secret_value())

    matched = project_registry.get_by_token_hash(token_hash_prefix)
    assert matched is not None
    assert matched.name == "remote-coder"


def test_get_by_token_hash_rejects_non_normalized_segment(project_registry: ProjectRegistry) -> None:
    project = project_registry.get("remote-coder")
    assert project is not None
    full = compute_token_hash(project.bot_token.get_secret_value())
    assert project_registry.get_by_token_hash(full) is None
    assert project_registry.get_by_token_hash(full[:15]) is None


def test_add_project_rejects_webhook_prefix_collision(isolate_remote_coder_home: Path, tmp_path: Path) -> None:
    path = isolate_remote_coder_home / "coll_add.json"
    root = tmp_path / "repo"
    root.mkdir(parents=True)
    reg = _seed_registry(path, root)
    existing = reg.get("remote-coder")
    assert existing is not None
    root2 = tmp_path / "repo2"
    root2.mkdir()

    with pytest.raises(ValueError, match="prefix collision"):
        reg.add_project(
            ProjectRecord(
                name="other",
                root_path=root2,
                default_model=ModelName.CLAUDE,
                enabled=True,
                bot_token=SecretStr(existing.bot_token.get_secret_value()),
                allowed_chat_ids=[123],
            )
        )


def test_update_project_rejects_webhook_prefix_collision(isolate_remote_coder_home: Path, tmp_path: Path) -> None:
    path = isolate_remote_coder_home / "coll_upd.json"
    root_a = tmp_path / "repo_a"
    root_a.mkdir()
    root_b = tmp_path / "repo_b"
    root_b.mkdir()
    reg = ProjectRegistry(path)
    reg.add_project(
        ProjectRecord(
            name="proj-a",
            root_path=root_a,
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


def test_keyring_backend_keeps_secrets_out_of_file(
    isolate_remote_coder_home: Path, tmp_path: Path
) -> None:
    # QAS-Sec-1: with an out-of-band store, no secret material lands in projects.json.
    path = isolate_remote_coder_home / "keyring-mode.json"
    root = tmp_path / "repo"
    root.mkdir(parents=True)
    store = InMemorySecretStore()
    reg = ProjectRegistry(path, store)
    reg.add_project(
        ProjectRecord(
            name="remote-coder",
            root_path=root,
            default_model=ModelName.CLAUDE,
            enabled=True,
            bot_token=SecretStr("super-secret-token"),
            webhook_secret=SecretStr("super-secret-webhook"),
            allowed_chat_ids=[123],
        )
    )

    raw = path.read_text(encoding="utf-8")
    assert "super-secret-token" not in raw
    assert "super-secret-webhook" not in raw
    assert json.loads(raw)["secret_backend"] == SECRET_BACKEND_KEYRING


def test_keyring_backend_round_trip_restores_secrets(
    isolate_remote_coder_home: Path, tmp_path: Path
) -> None:
    path = isolate_remote_coder_home / "keyring-roundtrip.json"
    root = tmp_path / "repo"
    root.mkdir(parents=True)
    store = InMemorySecretStore()
    reg = ProjectRegistry(path, store)
    reg.add_project(
        ProjectRecord(
            name="remote-coder",
            root_path=root,
            default_model=ModelName.CLAUDE,
            enabled=True,
            bot_token=SecretStr("super-secret-token"),
            webhook_secret=SecretStr("super-secret-webhook"),
            allowed_chat_ids=[123],
        )
    )

    reloaded = ProjectRegistry(path, store)
    reloaded.load()
    restored = reloaded.get("remote-coder")
    assert restored is not None
    assert restored.bot_token.get_secret_value() == "super-secret-token"
    assert restored.webhook_secret is not None
    assert restored.webhook_secret.get_secret_value() == "super-secret-webhook"
    # Token-hash routing still works because the in-memory token is restored.
    prefix = compute_token_hash_prefix("super-secret-token")
    assert reloaded.get_by_token_hash(prefix) is not None


def test_remove_project_deletes_keyring_secret(
    isolate_remote_coder_home: Path, tmp_path: Path
) -> None:
    # SC-9: deleting a project clears its out-of-band secrets (no orphan).
    path = isolate_remote_coder_home / "keyring-delete.json"
    root = tmp_path / "repo"
    root.mkdir(parents=True)
    store = InMemorySecretStore()
    reg = ProjectRegistry(path, store)
    reg.add_project(
        ProjectRecord(
            name="remote-coder",
            root_path=root,
            default_model=ModelName.CLAUDE,
            enabled=True,
            bot_token=SecretStr("token"),
            allowed_chat_ids=[123],
        )
    )
    reg.remove_project("remote-coder")
    assert store.delete_calls == 1
    with pytest.raises(RuntimeError):
        store.load("remote-coder", {})


def test_load_incomplete_projects_json_fails_validation(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    path = tmp_path / "projects.json"
    legacy = {
        "default_project": "p",
        "projects": [
            {
                "name": "p",
                "root_path": str(root),
                "default_model": "claude",
                "enabled": True,
            },
        ],
    }
    path.write_text(json.dumps(legacy), encoding="utf-8")
    reg = ProjectRegistry(path)
    with pytest.raises(ValidationError):
        reg.load()
