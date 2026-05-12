from __future__ import annotations

from pathlib import Path

from app.git.service import GitWorktreeService
from app.monitoring.events import EventLogger
from app.projects.registry import ProjectRegistry


def run_startup_project_pulls(
    *,
    pull_projects_on_server_startup_enabled: bool,
    project_registry: ProjectRegistry,
    git_service: GitWorktreeService,
    remote: str,
    system_log: EventLogger,
) -> None:
    if not pull_projects_on_server_startup_enabled:
        return

    roots: dict[Path, str] = {}
    for record in project_registry.list_projects():
        if not record.enabled:
            continue
        path = record.root_path.resolve()
        if path not in roots:
            roots[path] = record.name

    for root_path, project_name in roots.items():
        try:
            summary = git_service.pull_repository(root_path, remote)
            system_log.info("startup pull completed: %s", summary, project=project_name)
        except Exception:
            system_log.exception("startup pull failed", project=project_name)
