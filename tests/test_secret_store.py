import json
import logging
from pathlib import Path

import pytest

from app.projects import secret_store as ss
from app.projects.secret_store import (
    InMemorySecretStore,
    KeyringSecretStore,
    PlaintextSecretStore,
    SECRET_BACKEND_KEYRING,
    SECRET_BACKEND_PLAINTEXT,
    build_secret_store,
    file_has_plaintext_secrets,
    file_secret_backend,
    secret_store_for_file,
)


def test_plaintext_store_round_trip_keeps_secrets_inline() -> None:
    store = PlaintextSecretStore()
    storable: dict = {}
    store.store("p", "bot-token", "wh-secret", storable)
    assert storable["bot_token"] == "bot-token"
    assert storable["webhook_secret"] == "wh-secret"
    assert store.load("p", storable) == ("bot-token", "wh-secret")
    assert store.backend_name == SECRET_BACKEND_PLAINTEXT


def test_inmemory_store_round_trip_keeps_secrets_out_of_band() -> None:
    store = InMemorySecretStore()
    storable: dict = {}
    store.store("p", "bot-token", None, storable)
    # Mimics keyring: nothing secret leaks into the storable dict.
    assert "bot_token" not in storable
    assert "webhook_secret" not in storable
    assert store.load("p", {}) == ("bot-token", None)
    assert store.backend_name == SECRET_BACKEND_KEYRING


def test_inmemory_store_load_missing_fails_loud_without_secret() -> None:
    store = InMemorySecretStore()
    with pytest.raises(RuntimeError, match="'ghost'"):
        store.load("ghost", {})


def test_inmemory_store_delete_is_idempotent() -> None:
    store = InMemorySecretStore()
    store.store("p", "t", None, {})
    store.delete("p")
    store.delete("p")  # no raise on second delete
    assert store.delete_calls == 2


def _write_projects_json(path: Path, *, secret_backend: str | None, bot_token: str | None) -> None:
    project: dict = {"name": "p", "root_path": "/tmp", "enabled": True}
    if bot_token is not None:
        project["bot_token"] = bot_token
    data: dict = {"default_project": "p", "projects": [project]}
    if secret_backend is not None:
        data["secret_backend"] = secret_backend
    path.write_text(json.dumps(data), encoding="utf-8")


def test_file_secret_backend_reads_marker(tmp_path: Path) -> None:
    path = tmp_path / "projects.json"
    _write_projects_json(path, secret_backend=SECRET_BACKEND_KEYRING, bot_token=None)
    assert file_secret_backend(path) == SECRET_BACKEND_KEYRING


def test_file_secret_backend_defaults_to_plaintext(tmp_path: Path) -> None:
    path = tmp_path / "projects.json"
    _write_projects_json(path, secret_backend=None, bot_token="t")
    assert file_secret_backend(path) == SECRET_BACKEND_PLAINTEXT
    # Missing file also defaults to plaintext.
    assert file_secret_backend(tmp_path / "absent.json") == SECRET_BACKEND_PLAINTEXT


def test_file_has_plaintext_secrets_detects_inline_token(tmp_path: Path) -> None:
    path = tmp_path / "projects.json"
    _write_projects_json(path, secret_backend=None, bot_token="t")
    assert file_has_plaintext_secrets(path) is True
    _write_projects_json(path, secret_backend=SECRET_BACKEND_KEYRING, bot_token=None)
    assert file_has_plaintext_secrets(path) is False


def test_secret_store_for_file_matches_marker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "projects.json"
    _write_projects_json(path, secret_backend=SECRET_BACKEND_KEYRING, bot_token=None)
    assert isinstance(secret_store_for_file(path), KeyringSecretStore)
    _write_projects_json(path, secret_backend=None, bot_token="t")
    assert isinstance(secret_store_for_file(path), PlaintextSecretStore)


# --- build_secret_store fallback policy (D1) -------------------------------------------------


def test_build_secret_store_uses_keyring_when_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ss, "usable_keyring_backend", lambda: object())
    assert isinstance(build_secret_store(tmp_path / "projects.json"), KeyringSecretStore)


def test_build_secret_store_grandfathers_legacy_plaintext_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "projects.json"
    _write_projects_json(path, secret_backend=None, bot_token="legacy-token")
    monkeypatch.setattr(ss, "usable_keyring_backend", lambda: None)
    monkeypatch.delenv(ss.PLAINTEXT_OPT_IN_ENV, raising=False)
    with caplog.at_level(logging.WARNING):
        store = build_secret_store(path)
    assert isinstance(store, PlaintextSecretStore)
    assert any("PLAINTEXT" in rec.message for rec in caplog.records)
    assert "legacy-token" not in caplog.text


def test_build_secret_store_opt_in_plaintext_for_new_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "projects.json"  # no file yet
    monkeypatch.setattr(ss, "usable_keyring_backend", lambda: None)
    monkeypatch.setenv(ss.PLAINTEXT_OPT_IN_ENV, "1")
    with caplog.at_level(logging.WARNING):
        store = build_secret_store(path)
    assert isinstance(store, PlaintextSecretStore)
    assert any("PLAINTEXT" in rec.message for rec in caplog.records)


def test_build_secret_store_fails_closed_for_new_install_without_opt_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "projects.json"  # no file, no plaintext
    monkeypatch.setattr(ss, "usable_keyring_backend", lambda: None)
    monkeypatch.delenv(ss.PLAINTEXT_OPT_IN_ENV, raising=False)
    with pytest.raises(RuntimeError, match="No usable OS keyring backend"):
        build_secret_store(path)
