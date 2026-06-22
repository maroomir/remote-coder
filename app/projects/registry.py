from __future__ import annotations

import json
import re
from hashlib import sha256
from pathlib import Path
from threading import Lock
import yaml
from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator

from app.config import default_worktree_base_dir, resolve_state_path
from app.models import ModelName
from app.projects.secret_store import PlaintextSecretStore, SecretStore

_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

WEBHOOK_TOKEN_HASH_PREFIX_LENGTH = 16
_WEBHOOK_TOKEN_HASH_PREFIX_RE = re.compile(
    rf"^[0-9a-f]{{{WEBHOOK_TOKEN_HASH_PREFIX_LENGTH}}}$"
)


def compute_token_hash(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def compute_token_hash_prefix(token: str, length: int = WEBHOOK_TOKEN_HASH_PREFIX_LENGTH) -> str:
    return compute_token_hash(token)[:length]


def build_public_webhook_url(public_base_url: str, bot_token: str) -> str:
    base = public_base_url.strip().rstrip("/")
    prefix = compute_token_hash_prefix(bot_token.strip())
    return f"{base}/telegram/webhook/{prefix}"


def normalize_webhook_token_hash_path_segment(segment: str) -> str | None:
    s = segment.strip().lower()
    return s if _WEBHOOK_TOKEN_HASH_PREFIX_RE.fullmatch(s) else None


def mask_bot_token(token: str) -> str:
    if not token:
        return "(not set)"
    if len(token) <= 8:
        return "***"
    return f"***…{token[-4:]}"


def projects_config_path(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit.expanduser().resolve()
    return resolve_state_path("projects.json")


class ProjectRecord(BaseModel):
    model_config = {"extra": "forbid"}

    name: str
    root_path: Path
    # 입력값은 하위호환을 위해 받아두되 무시하고, name 기준으로 ~/.remote-coder/worktrees/<name> 로 도출한다.
    worktree_base_dir: Path | None = None
    default_model: ModelName = ModelName.CLAUDE
    enabled: bool = True
    bot_token: SecretStr
    webhook_secret: SecretStr | None = None
    allowed_chat_ids: list[int]
    allowed_user_ids: list[int] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not _NAME_PATTERN.match(value):
            raise ValueError(
                "project name must match ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$",
            )
        return value

    @field_validator("root_path", mode="before")
    @classmethod
    def expand_path(cls, value: object) -> Path:
        if isinstance(value, Path):
            return value.expanduser().resolve()
        if isinstance(value, str):
            return Path(value).expanduser().resolve()
        raise TypeError("path must be str or Path")

    @model_validator(mode="after")
    def _derive_worktree_base_dir(self) -> ProjectRecord:
        self.worktree_base_dir = default_worktree_base_dir(self.name)
        return self


class ProjectsFilePayload(BaseModel):
    model_config = {"extra": "forbid"}

    default_project: str
    projects: list[ProjectRecord] = Field(default_factory=list)


class ProjectRegistry:
    def __init__(self, config_path: Path, secret_store: SecretStore | None = None) -> None:
        self._path = config_path
        self._lock = Lock()
        self._payload = ProjectsFilePayload(default_project="", projects=[])
        self._secrets: SecretStore = secret_store or PlaintextSecretStore()

    @property
    def config_path(self) -> Path:
        return self._path

    def load(self) -> None:
        with self._lock:
            self._payload = self._read_file_unlocked()

    def ensure_empty_registry_file(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            empty = ProjectsFilePayload(default_project="", projects=[])
            with self._lock:
                self._payload = empty
                self._write_file_unlocked(empty)
            return
        self.load()

    def save(self) -> None:
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._write_file_unlocked(self._payload)

    def list_projects(self) -> list[ProjectRecord]:
        with self._lock:
            return list(self._payload.projects)

    def get(self, name: str) -> ProjectRecord | None:
        with self._lock:
            for p in self._payload.projects:
                if p.name == name:
                    return p.model_copy(deep=True)
        return None

    def get_by_token_hash(self, token_hash: str) -> ProjectRecord | None:
        normalized = normalize_webhook_token_hash_path_segment(token_hash)
        if normalized is None:
            return None
        with self._lock:
            for project in self._payload.projects:
                prefix = compute_token_hash_prefix(project.bot_token.get_secret_value())
                if prefix == normalized:
                    return project.model_copy(deep=True)
        return None

    def get_default_project_name(self) -> str:
        with self._lock:
            return self._payload.default_project

    def set_default_project(self, name: str) -> None:
        with self._lock:
            if not any(p.name == name for p in self._payload.projects):
                raise ValueError(f"unknown project: {name}")
            self._payload.default_project = name
            self._write_file_unlocked(self._payload)

    def add_project(self, record: ProjectRecord) -> None:
        record = record.model_copy(deep=True)
        self._validate_paths(record)
        with self._lock:
            if any(p.name == record.name for p in self._payload.projects):
                raise ValueError(f"project already exists: {record.name}")
            ProjectRegistry._raise_if_token_hash_prefix_collides(record, list(self._payload.projects))
            projects = list(self._payload.projects)
            projects.append(record)
            self._payload = ProjectsFilePayload(
                default_project=self._payload.default_project or record.name,
                projects=projects,
            )
            self._write_file_unlocked(self._payload)

    def update_project(self, name: str, record: ProjectRecord) -> None:
        record = record.model_copy(deep=True)
        if record.name != name:
            raise ValueError("cannot change project name via update; remove and add")
        self._validate_paths(record)
        with self._lock:
            projects = [p for p in self._payload.projects if p.name != name]
            if len(projects) == len(self._payload.projects):
                raise ValueError(f"unknown project: {name}")
            ProjectRegistry._raise_if_token_hash_prefix_collides(record, projects)
            projects.append(record)
            self._payload = ProjectsFilePayload(
                default_project=self._payload.default_project,
                projects=projects,
            )
            self._write_file_unlocked(self._payload)

    def remove_project(self, name: str) -> None:
        with self._lock:
            projects = [p for p in self._payload.projects if p.name != name]
            if len(projects) == len(self._payload.projects):
                raise ValueError(f"unknown project: {name}")
            new_default = self._payload.default_project
            if new_default == name and projects:
                new_default = projects[0].name
            elif not projects:
                new_default = ""
            self._payload = ProjectsFilePayload(default_project=new_default, projects=projects)
            self._write_file_unlocked(self._payload)
            # Drop the removed project's out-of-band secrets (no-op for plaintext).
            self._secrets.delete(name)

    def to_public_dict(self) -> dict:
        # 호출 측에서 이미 락을 잡고 있으면 데드락이 나므로, API 응답 용도로만 사용하세요.
        with self._lock:
            return {
                "default_project": self._payload.default_project,
                "projects": [
                    ProjectRegistry._project_record_to_public_dict(p) for p in self._payload.projects
                ],
            }

    @staticmethod
    def _project_record_to_public_dict(record: ProjectRecord) -> dict:
        token_plain = record.bot_token.get_secret_value()
        prefix = compute_token_hash_prefix(token_plain)
        secret_plain = (
            record.webhook_secret.get_secret_value().strip() if record.webhook_secret else ""
        )
        return {
            "name": record.name,
            "root_path": str(record.root_path),
            "worktree_base_dir": str(record.worktree_base_dir),
            "default_model": record.default_model.value,
            "enabled": record.enabled,
            "bot_token_masked": mask_bot_token(token_plain),
            "webhook_secret_set": bool(secret_plain),
            "allowed_chat_ids": list(record.allowed_chat_ids),
            "allowed_user_ids": list(record.allowed_user_ids),
            "webhook_path": f"/telegram/webhook/{prefix}",
            "token_hash_prefix": prefix,
        }

    @staticmethod
    def _raise_if_token_hash_prefix_collides(record: ProjectRecord, existing: list[ProjectRecord]) -> None:
        prefix = compute_token_hash_prefix(record.bot_token.get_secret_value())
        for p in existing:
            if compute_token_hash_prefix(p.bot_token.get_secret_value()) == prefix:
                raise ValueError(
                    f"webhook token hash prefix collision with project {p.name!r}",
                )

    def _read_file_unlocked(self) -> ProjectsFilePayload:
        if not self._path.exists():
            return ProjectsFilePayload(default_project="", projects=[])
        raw = self._path.read_text(encoding="utf-8")
        if self._path.suffix.lower() in (".yaml", ".yml"):
            data = yaml.safe_load(raw) or {}
        else:
            data = json.loads(raw) if raw.strip() else {}
        if isinstance(data, dict):
            # secret_backend is file-only metadata; the injected store decides how to read.
            data.pop("secret_backend", None)
            data["projects"] = [self._inject_secrets(p) for p in data.get("projects") or []]
        return ProjectsFilePayload.model_validate(data)

    def _inject_secrets(self, project: dict) -> dict:
        if not isinstance(project, dict):
            return project
        project = dict(project)
        bot_token, webhook_secret = self._secrets.load(project.get("name", ""), project)
        if bot_token is not None:
            project["bot_token"] = bot_token
        project["webhook_secret"] = webhook_secret
        return project

    def _write_file_unlocked(self, payload: ProjectsFilePayload) -> None:
        storable = self._payload_to_storable_dict(payload)
        if self._path.suffix.lower() in (".yaml", ".yml"):
            text = yaml.safe_dump(storable, allow_unicode=True, default_flow_style=False)
        else:
            text = json.dumps(storable, indent=2, ensure_ascii=False)
        self._path.write_text(text + "\n", encoding="utf-8")
        # Bot tokens and webhook secrets live here in plaintext, so keep the file
        # and its directory readable only by the owner (PLAN.md N1, SECURITY.md).
        self._path.chmod(0o600)
        try:
            self._path.parent.chmod(0o700)
        except OSError:
            pass

    def _project_record_to_storable_dict(self, record: ProjectRecord) -> dict:
        # worktree_base_dir 는 name 기준으로 항상 도출하므로 저장하지 않는다.
        data = record.model_dump(
            mode="json", exclude={"bot_token", "webhook_secret", "worktree_base_dir"}
        )
        # The secret store decides where secrets go: inline (plaintext) or out of band (keyring).
        self._secrets.store(
            record.name,
            record.bot_token.get_secret_value(),
            record.webhook_secret.get_secret_value() if record.webhook_secret else None,
            data,
        )
        return data

    def _payload_to_storable_dict(self, payload: ProjectsFilePayload) -> dict:
        return {
            "default_project": payload.default_project,
            "secret_backend": self._secrets.backend_name,
            "projects": [
                self._project_record_to_storable_dict(p) for p in payload.projects
            ],
        }

    @staticmethod
    def _validate_paths(record: ProjectRecord) -> None:
        root = record.root_path
        if not root.exists():
            raise ValueError(f"root_path does not exist: {root}")
        if not root.is_dir():
            raise ValueError(f"root_path is not a directory: {root}")
        wt = record.worktree_base_dir
        wt.mkdir(parents=True, exist_ok=True)
