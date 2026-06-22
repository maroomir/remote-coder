"""Secret persistence backends for project bot tokens and webhook secrets.

`ProjectRegistry` keeps secrets in memory as ``SecretStr`` and delegates *where they
are persisted* to a ``SecretStore``. The plaintext backend keeps them inline in
``projects.json`` (legacy / opt-in); the keyring backend stores them in the OS keyring
(macOS Keychain / Linux Secret Service / Windows Credential Locker) so nothing secret
is written to disk. Adding another backend means implementing this one interface only.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Protocol, runtime_checkable

import yaml

_log = logging.getLogger("app.projects.secret_store")

KEYRING_SERVICE = "remote-coder"

SECRET_BACKEND_KEYRING = "keyring"
SECRET_BACKEND_PLAINTEXT = "plaintext"

PLAINTEXT_OPT_IN_ENV = "REMOTE_CODER_ALLOW_PLAINTEXT_SECRETS"

_BOT_TOKEN_FIELD = "bot_token"
_WEBHOOK_SECRET_FIELD = "webhook_secret"
_TRUE_VALUES = {"1", "true", "yes", "on"}


@runtime_checkable
class SecretStore(Protocol):
    """Where a project's bot token and webhook secret are persisted.

    ``store``/``load`` exchange a ``storable`` dict so the plaintext backend can put
    secrets inline while the keyring backend leaves the dict untouched and uses the OS
    keyring out of band — both share one signature.
    """

    backend_name: str

    def store(
        self, project_name: str, bot_token: str, webhook_secret: str | None, storable: dict
    ) -> None: ...

    def load(self, project_name: str, storable: dict) -> tuple[str | None, str | None]: ...

    def delete(self, project_name: str) -> None: ...


class PlaintextSecretStore:
    """Keeps secrets inline in ``projects.json``. Legacy default and opt-in fallback."""

    backend_name = SECRET_BACKEND_PLAINTEXT

    def store(
        self, project_name: str, bot_token: str, webhook_secret: str | None, storable: dict
    ) -> None:
        storable[_BOT_TOKEN_FIELD] = bot_token
        storable[_WEBHOOK_SECRET_FIELD] = webhook_secret

    def load(self, project_name: str, storable: dict) -> tuple[str | None, str | None]:
        return storable.get(_BOT_TOKEN_FIELD), storable.get(_WEBHOOK_SECRET_FIELD)

    def delete(self, project_name: str) -> None:
        # The secret lives in the file; removing the project rewrites the file without it.
        return None


class KeyringSecretStore:
    """Stores secrets in the OS keyring, keyed by ``<project_name>:<field>``."""

    backend_name = SECRET_BACKEND_KEYRING

    def store(
        self, project_name: str, bot_token: str, webhook_secret: str | None, storable: dict
    ) -> None:
        import keyring

        keyring.set_password(KEYRING_SERVICE, self._account(project_name, _BOT_TOKEN_FIELD), bot_token)
        secret_account = self._account(project_name, _WEBHOOK_SECRET_FIELD)
        if webhook_secret:
            keyring.set_password(KEYRING_SERVICE, secret_account, webhook_secret)
        else:
            self._delete_quietly(secret_account)

    def load(self, project_name: str, storable: dict) -> tuple[str | None, str | None]:
        import keyring

        bot_token = keyring.get_password(KEYRING_SERVICE, self._account(project_name, _BOT_TOKEN_FIELD))
        if bot_token is None:
            # Fail loud with the project name only — never echo secret material (QAS-Sec-2).
            raise RuntimeError(
                f"bot token for project {project_name!r} was not found in the OS keyring"
            )
        webhook_secret = keyring.get_password(
            KEYRING_SERVICE, self._account(project_name, _WEBHOOK_SECRET_FIELD)
        )
        return bot_token, webhook_secret

    def delete(self, project_name: str) -> None:
        self._delete_quietly(self._account(project_name, _BOT_TOKEN_FIELD))
        self._delete_quietly(self._account(project_name, _WEBHOOK_SECRET_FIELD))

    @staticmethod
    def _account(project_name: str, field: str) -> str:
        return f"{project_name}:{field}"

    @staticmethod
    def _delete_quietly(account: str) -> None:
        import keyring
        import keyring.errors

        try:
            keyring.delete_password(KEYRING_SERVICE, account)
        except keyring.errors.PasswordDeleteError:
            pass
        except Exception as exc:  # backend hiccup — log without the secret value
            _log.warning("keyring delete failed account=%s err=%s", account, exc)


class InMemorySecretStore:
    """Out-of-band store for tests; mimics the keyring backend without touching the OS.

    Like the keyring backend, it never writes secrets into ``storable`` and reports
    ``backend_name = "keyring"`` so persisted files are marked the same way.
    """

    backend_name = SECRET_BACKEND_KEYRING

    def __init__(self) -> None:
        self._secrets: dict[str, tuple[str, str | None]] = {}
        self.store_calls = 0
        self.load_calls = 0
        self.delete_calls = 0

    def store(
        self, project_name: str, bot_token: str, webhook_secret: str | None, storable: dict
    ) -> None:
        self.store_calls += 1
        self._secrets[project_name] = (bot_token, webhook_secret)

    def load(self, project_name: str, storable: dict) -> tuple[str | None, str | None]:
        self.load_calls += 1
        if project_name not in self._secrets:
            raise RuntimeError(
                f"bot token for project {project_name!r} was not found in the secret store"
            )
        return self._secrets[project_name]

    def delete(self, project_name: str) -> None:
        self.delete_calls += 1
        self._secrets.pop(project_name, None)


_PROBE_ACCOUNT = "__remote_coder_keyring_probe__"


def usable_keyring_backend() -> object | None:
    """Return the active OS keyring backend if it can actually store secrets, else None.

    The ``fail``/``null`` backends are rejected up front; everything else is confirmed with
    an active set/get/delete probe, so a locked keychain or a chainer backend wrapping only
    unusable backends is correctly treated as unavailable.
    """
    try:
        import keyring
        from keyring.backends import fail
    except Exception:
        return None
    try:
        backend = keyring.get_keyring()
    except Exception:
        return None
    if isinstance(backend, fail.Keyring):
        return None
    try:
        from keyring.backends import null

        if isinstance(backend, null.Keyring):
            return None
    except Exception:
        pass

    try:
        keyring.set_password(KEYRING_SERVICE, _PROBE_ACCOUNT, "ok")
        usable = keyring.get_password(KEYRING_SERVICE, _PROBE_ACCOUNT) == "ok"
    except Exception:
        return None
    finally:
        try:
            keyring.delete_password(KEYRING_SERVICE, _PROBE_ACCOUNT)
        except Exception:
            pass
    return backend if usable else None


def file_secret_backend(projects_path: Path) -> str:
    """Read the ``secret_backend`` marker persisted in ``projects.json`` (default plaintext)."""
    data = _read_projects_file(projects_path)
    marker = str(data.get("secret_backend") or "").strip().lower()
    return SECRET_BACKEND_KEYRING if marker == SECRET_BACKEND_KEYRING else SECRET_BACKEND_PLAINTEXT


def file_has_plaintext_secrets(projects_path: Path) -> bool:
    """True when any project still carries an inline plaintext ``bot_token``."""
    data = _read_projects_file(projects_path)
    for project in data.get("projects", []) or []:
        if isinstance(project, dict) and str(project.get(_BOT_TOKEN_FIELD) or "").strip():
            return True
    return False


def secret_store_for_file(projects_path: Path) -> SecretStore:
    """Pick the store that matches how ``projects.json`` is currently persisted.

    Used by read-only entry points (CLI, webhook registration) so they read correctly
    whether or not the one-time keyring migration has run yet.
    """
    if file_secret_backend(projects_path) == SECRET_BACKEND_KEYRING:
        return KeyringSecretStore()
    return PlaintextSecretStore()


def build_secret_store(projects_path: Path) -> SecretStore:
    """Select the target backend for new writes, enforcing the fallback policy (D1).

    keyring available -> keyring. Otherwise: keep plaintext (with a warning) when a
    legacy plaintext file already exists or the opt-in env var is set; else fail closed
    so a fresh install never silently writes secrets in plaintext.
    """
    if usable_keyring_backend() is not None:
        return KeyringSecretStore()

    if file_has_plaintext_secrets(projects_path):
        _log.warning(
            "No usable OS keyring backend; keeping PLAINTEXT secrets in %s (existing legacy "
            "file). Secrets are NOT encrypted at rest.",
            projects_path,
        )
        return PlaintextSecretStore()

    if os.environ.get(PLAINTEXT_OPT_IN_ENV, "").strip().lower() in _TRUE_VALUES:
        _log.warning(
            "No usable OS keyring backend; %s is set, so secrets will be stored as PLAINTEXT "
            "in %s. Secrets are NOT encrypted at rest.",
            PLAINTEXT_OPT_IN_ENV,
            projects_path,
        )
        return PlaintextSecretStore()

    raise RuntimeError(
        "No usable OS keyring backend is available, so bot tokens cannot be stored securely. "
        "Install a keyring backend (macOS Keychain / Linux Secret Service / Windows Credential "
        f"Locker), or set {PLAINTEXT_OPT_IN_ENV}=1 to store secrets as plaintext in projects.json "
        "(not recommended)."
    )


def _read_projects_file(projects_path: Path) -> dict:
    if not projects_path.exists():
        return {}
    try:
        raw = projects_path.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        if projects_path.suffix.lower() in (".yaml", ".yml"):
            data = yaml.safe_load(raw) or {}
        else:
            data = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}
