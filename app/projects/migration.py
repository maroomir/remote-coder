"""One-time migration of plaintext projects.json secrets into a SecretStore (keyring).

Runs at server startup (never on import) when the keyring backend is active. Existing
plaintext bot tokens are moved into the keyring, verified by read-back, and stripped
from the file in an atomic rewrite. A timestamp-free ``.pre-keyring.bak`` backup is left
behind so a downgrade can restore the previous plaintext file.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import yaml

from app.projects.secret_store import SECRET_BACKEND_KEYRING, SecretStore

_log = logging.getLogger("app.projects.migration")

_BOT_TOKEN_FIELD = "bot_token"
_WEBHOOK_SECRET_FIELD = "webhook_secret"


def migrate_plaintext_to_keyring(projects_path: Path, secret_store: SecretStore) -> int:
    """Move inline plaintext secrets into ``secret_store`` once. Idempotent; returns count moved."""
    if not projects_path.exists():
        return 0
    raw = projects_path.read_text(encoding="utf-8")
    is_yaml = _is_yaml(projects_path)
    data = _parse(raw, is_yaml)
    projects = data.get("projects") or []
    plaintext_projects = [
        project
        for project in projects
        if isinstance(project, dict) and str(project.get(_BOT_TOKEN_FIELD) or "").strip()
    ]
    if not plaintext_projects:
        return 0  # Already migrated or nothing to move — idempotent no-op.

    backup = projects_path.with_name(projects_path.name + ".pre-keyring.bak")
    backup.write_text(raw, encoding="utf-8")
    _chmod_owner_only(backup)

    written_names: list[str] = []
    try:
        for project in plaintext_projects:
            name = project.get("name")
            token = project.get(_BOT_TOKEN_FIELD)
            secret = project.get(_WEBHOOK_SECRET_FIELD)
            secret_store.store(name, token, secret, {})
            written_names.append(name)
            stored_token, stored_secret = secret_store.load(name, {})
            if stored_token != token or stored_secret != secret:
                raise RuntimeError(
                    f"secret store read-back verification failed for project {name!r}"
                )

        # Strip secrets only from projects we actually moved to the keyring; leave others as-is.
        migrated = set(written_names)
        cleaned = dict(data)
        cleaned["secret_backend"] = SECRET_BACKEND_KEYRING
        cleaned["projects"] = [
            _strip_secrets(project) if project.get("name") in migrated else project
            for project in projects
        ]
        _atomic_write(projects_path, cleaned, is_yaml)
    except Exception:
        # Roll back only the keyring writes this run made; the untouched file stays the source of truth.
        for name in written_names:
            try:
                secret_store.delete(name)
            except Exception:
                pass
        backup.unlink(missing_ok=True)
        raise

    _log.warning(
        "Moved %d project secret(s) into the OS keyring and removed plaintext from %s (backup: %s).",
        len(plaintext_projects),
        projects_path,
        backup.name,
    )
    return len(plaintext_projects)


def mark_secret_backend(projects_path: Path, backend_name: str) -> None:
    """Persist the ``secret_backend`` marker so a fresh/empty registry adopts the active backend."""
    is_yaml = _is_yaml(projects_path)
    if projects_path.exists():
        data = _parse(projects_path.read_text(encoding="utf-8"), is_yaml)
        if data.get("secret_backend") == backend_name:
            return
    else:
        data = {"default_project": "", "projects": []}
    data = dict(data)
    data["secret_backend"] = backend_name
    _atomic_write(projects_path, data, is_yaml)


def _is_yaml(projects_path: Path) -> bool:
    return projects_path.suffix.lower() in (".yaml", ".yml")


def _parse(raw: str, is_yaml: bool) -> dict:
    if is_yaml:
        data = yaml.safe_load(raw) or {}
    else:
        data = json.loads(raw) if raw.strip() else {}
    return data if isinstance(data, dict) else {}


def _strip_secrets(project: dict) -> dict:
    if not isinstance(project, dict):
        return project
    project = dict(project)
    project.pop(_BOT_TOKEN_FIELD, None)
    project.pop(_WEBHOOK_SECRET_FIELD, None)
    return project


def _atomic_write(projects_path: Path, data: dict, is_yaml: bool) -> None:
    projects_path.parent.mkdir(parents=True, exist_ok=True)
    if is_yaml:
        text = yaml.safe_dump(data, allow_unicode=True, default_flow_style=False)
    else:
        text = json.dumps(data, indent=2, ensure_ascii=False)
    tmp = projects_path.with_name(projects_path.name + ".tmp")
    tmp.write_text(text + "\n", encoding="utf-8")
    _chmod_owner_only(tmp)
    os.replace(tmp, projects_path)
    _chmod_owner_only(projects_path)
    try:
        projects_path.parent.chmod(0o700)
    except OSError:
        pass


def _chmod_owner_only(path: Path) -> None:
    try:
        path.chmod(0o600)
    except OSError:
        pass
