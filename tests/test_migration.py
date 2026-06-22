import json
import stat
from pathlib import Path

import pytest

from app.projects.migration import mark_secret_backend, migrate_plaintext_to_keyring
from app.projects.secret_store import SECRET_BACKEND_KEYRING, InMemorySecretStore


def _write_plaintext_registry(path: Path, *, names: list[str]) -> None:
    projects = [
        {
            "name": name,
            "root_path": "/tmp/repo",
            "default_model": "claude",
            "enabled": True,
            "bot_token": f"{name}-secret-token",
            "webhook_secret": f"{name}-secret-webhook",
            "allowed_chat_ids": [123],
            "allowed_user_ids": [],
        }
        for name in names
    ]
    path.write_text(
        json.dumps({"default_project": names[0], "projects": projects}, indent=2),
        encoding="utf-8",
    )


def test_migration_moves_secrets_and_strips_plaintext(tmp_path: Path) -> None:
    path = tmp_path / "projects.json"
    _write_plaintext_registry(path, names=["alpha", "beta"])
    store = InMemorySecretStore()

    moved = migrate_plaintext_to_keyring(path, store)

    assert moved == 2
    raw = path.read_text(encoding="utf-8")
    # QAS-Sec-1: no secret material remains in the file.
    assert "secret-token" not in raw
    assert "secret-webhook" not in raw
    data = json.loads(raw)
    assert data["secret_backend"] == SECRET_BACKEND_KEYRING
    # Metadata is preserved (QAS-Compat-2).
    assert {p["name"] for p in data["projects"]} == {"alpha", "beta"}
    assert store.load("alpha", {}) == ("alpha-secret-token", "alpha-secret-webhook")


def test_migration_creates_owner_only_backup(tmp_path: Path) -> None:
    path = tmp_path / "projects.json"
    _write_plaintext_registry(path, names=["alpha"])
    original = path.read_text(encoding="utf-8")

    migrate_plaintext_to_keyring(path, InMemorySecretStore())

    backup = tmp_path / "projects.json.pre-keyring.bak"
    assert backup.exists()
    assert backup.read_text(encoding="utf-8") == original
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600


def test_migration_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "projects.json"
    _write_plaintext_registry(path, names=["alpha"])
    store = InMemorySecretStore()

    first = migrate_plaintext_to_keyring(path, store)
    after_first = path.read_text(encoding="utf-8")
    calls_after_first = store.store_calls

    second = migrate_plaintext_to_keyring(path, store)
    third = migrate_plaintext_to_keyring(path, store)

    assert first == 1
    assert second == 0 and third == 0
    # QAS-Compat-1: no further store writes and the file is unchanged.
    assert store.store_calls == calls_after_first
    assert path.read_text(encoding="utf-8") == after_first


def test_migration_no_op_when_no_plaintext(tmp_path: Path) -> None:
    path = tmp_path / "projects.json"
    path.write_text(
        json.dumps({"default_project": "", "projects": [], "secret_backend": "keyring"}),
        encoding="utf-8",
    )
    assert migrate_plaintext_to_keyring(path, InMemorySecretStore()) == 0
    assert migrate_plaintext_to_keyring(tmp_path / "absent.json", InMemorySecretStore()) == 0


def test_migration_rolls_back_on_store_failure(tmp_path: Path) -> None:
    path = tmp_path / "projects.json"
    _write_plaintext_registry(path, names=["alpha", "beta"])
    original = path.read_text(encoding="utf-8")

    class FailingStore(InMemorySecretStore):
        def store(self, project_name, bot_token, webhook_secret, storable):
            if project_name == "beta":
                raise RuntimeError("keyring write failed")
            super().store(project_name, bot_token, webhook_secret, storable)

    store = FailingStore()
    with pytest.raises(RuntimeError, match="keyring write failed"):
        migrate_plaintext_to_keyring(path, store)

    # QAS-Compat-3: original file is byte-for-byte unchanged and rollback is clean.
    assert path.read_text(encoding="utf-8") == original
    assert not (tmp_path / "projects.json.pre-keyring.bak").exists()
    assert store._secrets == {}


def test_mark_secret_backend_creates_parent_directory(tmp_path: Path) -> None:
    # C1: a fresh install has no ~/.remote-coder yet when the keyring marker is written.
    path = tmp_path / "nonexistent" / "projects.json"
    mark_secret_backend(path, SECRET_BACKEND_KEYRING)
    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8"))["secret_backend"] == SECRET_BACKEND_KEYRING


def test_migration_preserves_secrets_of_non_token_projects(tmp_path: Path) -> None:
    # M1: only token-bearing projects are migrated; others keep their inline data untouched.
    path = tmp_path / "projects.json"
    data = {
        "default_project": "alpha",
        "projects": [
            {"name": "alpha", "root_path": "/tmp/a", "enabled": True,
             "bot_token": "alpha-token", "webhook_secret": "alpha-wh", "allowed_chat_ids": [1]},
            {"name": "gamma", "root_path": "/tmp/g", "enabled": True,
             "webhook_secret": "gamma-only-webhook", "allowed_chat_ids": [2]},
        ],
    }
    path.write_text(json.dumps(data), encoding="utf-8")

    moved = migrate_plaintext_to_keyring(path, InMemorySecretStore())

    assert moved == 1
    result = json.loads(path.read_text(encoding="utf-8"))
    gamma = next(p for p in result["projects"] if p["name"] == "gamma")
    assert gamma["webhook_secret"] == "gamma-only-webhook"
    alpha = next(p for p in result["projects"] if p["name"] == "alpha")
    assert "bot_token" not in alpha and "webhook_secret" not in alpha


def test_migration_rollback_keeps_unrelated_keyring_entries(tmp_path: Path) -> None:
    # H1: a store failure rolls back only this run's writes, not pre-existing keyring entries.
    path = tmp_path / "projects.json"
    _write_plaintext_registry(path, names=["alpha", "beta"])

    class FailingStore(InMemorySecretStore):
        def store(self, project_name, bot_token, webhook_secret, storable):
            if project_name == "beta":
                raise RuntimeError("keyring write failed")
            super().store(project_name, bot_token, webhook_secret, storable)

    store = FailingStore()
    store.store("gamma", "pre-existing-token", None, {})  # legitimate prior entry

    with pytest.raises(RuntimeError, match="keyring write failed"):
        migrate_plaintext_to_keyring(path, store)

    assert store.load("gamma", {}) == ("pre-existing-token", None)  # survived rollback


def test_mark_secret_backend_creates_marked_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "projects.json"
    mark_secret_backend(path, SECRET_BACKEND_KEYRING)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["secret_backend"] == SECRET_BACKEND_KEYRING
    assert data["projects"] == []


def test_mark_secret_backend_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "projects.json"
    _write_plaintext_registry(path, names=["alpha"])
    mark_secret_backend(path, SECRET_BACKEND_KEYRING)
    first = path.read_text(encoding="utf-8")
    mark_secret_backend(path, SECRET_BACKEND_KEYRING)
    assert path.read_text(encoding="utf-8") == first
