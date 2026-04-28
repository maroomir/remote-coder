from __future__ import annotations

import json
import re
from pathlib import Path
from threading import Lock
import yaml
from pydantic import BaseModel, Field, field_validator

from app.config import Settings
from app.models import ModelName

_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def projects_config_path_for_settings(project_root: Path, explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit.expanduser().resolve()
    return (project_root / ".remote-coder" / "projects.json").resolve()


class ProjectRecord(BaseModel):
    """단일 등록 프로젝트."""

    model_config = {"extra": "forbid"}

    name: str
    root_path: Path
    worktree_base_dir: Path
    default_model: ModelName = ModelName.CLAUDE
    enabled: bool = True

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not _NAME_PATTERN.match(value):
            raise ValueError(
                "project name must match ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$",
            )
        return value

    @field_validator("root_path", "worktree_base_dir", mode="before")
    @classmethod
    def expand_path(cls, value: object) -> Path:
        if isinstance(value, Path):
            return value.expanduser().resolve()
        if isinstance(value, str):
            return Path(value).expanduser().resolve()
        raise TypeError("path must be str or Path")


class ProjectsFilePayload(BaseModel):
    """디스크에 저장되는 전체 구조."""

    model_config = {"extra": "forbid"}

    default_project: str
    projects: list[ProjectRecord] = Field(default_factory=list)


class ProjectRegistry:
    """파일 기반 프로젝트 등록소. 스레드 안전 읽기/쓰기."""

    def __init__(self, config_path: Path) -> None:
        self._path = config_path
        self._lock = Lock()
        self._payload = ProjectsFilePayload(default_project="", projects=[])

    @property
    def config_path(self) -> Path:
        return self._path

    def load(self) -> None:
        with self._lock:
            self._payload = self._read_file_unlocked()

    def ensure_seeded_from_settings(self, settings: Settings) -> None:
        """설정 파일이 없으면 .env 기반 기본 프로젝트로 생성."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if self._path.exists():
            self.load()
            return
        seed = ProjectsFilePayload(
            default_project=settings.default_project,
            projects=[
                ProjectRecord(
                    name=settings.default_project,
                    root_path=settings.project_root,
                    worktree_base_dir=settings.worktree_base_dir,
                    default_model=settings.default_model,
                    enabled=True,
                )
            ],
        )
        with self._lock:
            self._payload = seed
            self._write_file_unlocked(seed)

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

    def get_default_project_name(self) -> str:
        with self._lock:
            return self._payload.default_project

    def project_names(self) -> list[str]:
        with self._lock:
            return [p.name for p in self._payload.projects if p.enabled]

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

    def to_public_dict(self) -> dict:
        """API 응답용 (락 보유 중 호출 금지 — 외부에서 load 후 사용)."""
        with self._lock:
            return {
                "default_project": self._payload.default_project,
                "projects": [p.model_dump(mode="json") for p in self._payload.projects],
            }

    def _read_file_unlocked(self) -> ProjectsFilePayload:
        if not self._path.exists():
            return ProjectsFilePayload(default_project="", projects=[])
        raw = self._path.read_text(encoding="utf-8")
        if self._path.suffix.lower() in (".yaml", ".yml"):
            data = yaml.safe_load(raw) or {}
        else:
            data = json.loads(raw) if raw.strip() else {}
        return ProjectsFilePayload.model_validate(data)

    def _write_file_unlocked(self, payload: ProjectsFilePayload) -> None:
        if self._path.suffix.lower() in (".yaml", ".yml"):
            text = yaml.safe_dump(
                payload.model_dump(mode="json"),
                allow_unicode=True,
                default_flow_style=False,
            )
        else:
            text = json.dumps(payload.model_dump(mode="json"), indent=2, ensure_ascii=False)
        self._path.write_text(text + "\n", encoding="utf-8")

    @staticmethod
    def _validate_paths(record: ProjectRecord) -> None:
        root = record.root_path
        if not root.exists():
            raise ValueError(f"root_path does not exist: {root}")
        if not root.is_dir():
            raise ValueError(f"root_path is not a directory: {root}")
        wt = record.worktree_base_dir
        wt.mkdir(parents=True, exist_ok=True)
