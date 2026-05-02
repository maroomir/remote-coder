from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from app.admin.advanced_settings import AdvancedSettings, FileAdvancedSettingsStore
from app.config import Settings
from app.models import ModelName
from app.monitoring.log_buffer import InMemoryLogBuffer
from app.projects.registry import ProjectRecord, ProjectRegistry


def _client_host(request: Request) -> str:
    if request.client is None:
        return ""
    return request.client.host or ""


def require_localhost(request: Request) -> None:
    host = _client_host(request)
    if host in ("127.0.0.1", "::1", "localhost", "testclient"):
        return
    raise HTTPException(status_code=403, detail="관리 UI는 로컬호스트에서만 사용할 수 있습니다.")


LocalhostOnly = Annotated[None, Depends(require_localhost)]


def _mask_bot_token(token: str) -> str:
    if not token:
        return "(설정 안 됨)"
    if len(token) <= 8:
        return "***"
    return f"***…{token[-4:]}"


class ProjectUpsertBody(BaseModel):
    name: str
    root_path: str
    worktree_base_dir: str
    default_model: ModelName = ModelName.CLAUDE
    enabled: bool = True


class DefaultProjectBody(BaseModel):
    name: str = Field(min_length=1)


_ADMIN_ICON_NAMES = frozenset({"home.svg", "projects.svg", "advanced.svg", "logs.svg"})


@lru_cache(maxsize=8)
def _load_template_html(template_name: str) -> str:
    template_path = Path(__file__).parent / "templates" / template_name
    return template_path.read_text(encoding="utf-8")


def create_admin_router(
    settings: Settings,
    registry: ProjectRegistry,
    advanced_settings_store: FileAdvancedSettingsStore,
    log_buffer: InMemoryLogBuffer,
) -> APIRouter:
    router = APIRouter(tags=["admin"])

    @router.get("/", response_class=HTMLResponse)
    def admin_hub(_: LocalhostOnly) -> str:
        return _load_template_html("admin.html")

    @router.get("/projects", response_class=HTMLResponse)
    def admin_projects(_: LocalhostOnly) -> str:
        return _load_template_html("projects.html")

    @router.get("/advanced", response_class=HTMLResponse)
    def admin_advanced(_: LocalhostOnly) -> str:
        return _load_template_html("advanced.html")

    @router.get("/logs", response_class=HTMLResponse)
    def admin_logs(_: LocalhostOnly) -> str:
        return _load_template_html("logs.html")

    @router.get("/api/logs")
    def api_logs(
        _: LocalhostOnly,
        limit: int = Query(200, ge=1, le=1000),
        after_id: int | None = Query(None, ge=1),
        level: str | None = Query(None, description="최소 로그 레벨 (DEBUG, INFO, WARNING, ERROR, CRITICAL)"),
        q: str | None = Query(None, max_length=500),
        logger: str | None = Query(None, max_length=200),
    ) -> dict[str, object]:
        q_clean = q.strip() if q else None
        if q_clean == "":
            q_clean = None
        logger_clean = logger.strip() if logger else None
        if logger_clean == "":
            logger_clean = None
        level_clean = level.strip() if level else None
        if level_clean == "":
            level_clean = None
        try:
            entries, max_seen = log_buffer.query(
                limit=limit,
                after_id=after_id,
                min_level=level_clean,
                q=q_clean,
                logger_sub=logger_clean,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "entries": entries,
            "max_id": max_seen,
            "max_entries": log_buffer.max_entries,
        }

    @router.get("/api/settings")
    def api_settings(_: LocalhostOnly) -> dict:
        token = settings.telegram_bot_token.get_secret_value()
        return {
            "telegram_bot_token_masked": _mask_bot_token(token),
            "telegram_allowed_chat_ids": settings.telegram_allowed_chat_ids,
            "telegram_allowed_user_ids": settings.telegram_allowed_user_ids,
            "telegram_webhook_secret_set": bool(settings.telegram_webhook_secret),
            "default_model_env": settings.default_model.value,
            "projects_config_path": str(registry.config_path),
            "webhook_hint": "Webhook URL은 ./run.sh 또는 scripts/set_webhook.py 로 등록합니다. "
            "경로: POST /telegram/webhook",
        }

    @router.get("/api/projects")
    def api_projects_get(_: LocalhostOnly) -> JSONResponse:
        return JSONResponse(registry.to_public_dict())

    @router.post("/api/projects")
    def api_projects_create(body: ProjectUpsertBody, _: LocalhostOnly) -> JSONResponse:
        record = ProjectRecord(
            name=body.name,
            root_path=body.root_path,
            worktree_base_dir=body.worktree_base_dir,
            default_model=body.default_model,
            enabled=body.enabled,
        )
        try:
            registry.add_project(record)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(registry.to_public_dict())

    @router.put("/api/projects/{name}")
    def api_projects_update(name: str, body: ProjectUpsertBody, _: LocalhostOnly) -> JSONResponse:
        record = ProjectRecord(
            name=body.name,
            root_path=body.root_path,
            worktree_base_dir=body.worktree_base_dir,
            default_model=body.default_model,
            enabled=body.enabled,
        )
        try:
            registry.update_project(name, record)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(registry.to_public_dict())

    @router.delete("/api/projects/{name}")
    def api_projects_delete(name: str, _: LocalhostOnly) -> JSONResponse:
        try:
            registry.remove_project(name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(registry.to_public_dict())

    @router.post("/api/projects/default")
    def api_projects_set_default(body: DefaultProjectBody, _: LocalhostOnly) -> JSONResponse:
        try:
            registry.set_default_project(body.name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(registry.to_public_dict())

    @router.get("/api/advanced-settings")
    def api_advanced_settings_get(_: LocalhostOnly) -> dict:
        return advanced_settings_store.get().model_dump(mode="json")

    @router.put("/api/advanced-settings")
    def api_advanced_settings_put(body: AdvancedSettings, _: LocalhostOnly) -> dict:
        return advanced_settings_store.save(body).model_dump(mode="json")

    @router.get("/admin-static/icons/{filename}")
    def admin_icon(filename: str, _: LocalhostOnly) -> FileResponse:
        if filename not in _ADMIN_ICON_NAMES:
            raise HTTPException(status_code=404, detail="not found")
        path = Path(__file__).parent / "static" / "icons" / filename
        if not path.is_file():
            raise HTTPException(status_code=404, detail="not found")
        return FileResponse(path, media_type="image/svg+xml")

    return router
