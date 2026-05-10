from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, SecretStr

from app.admin.advanced_settings import AdvancedSettings, FileAdvancedSettingsStore
from app.admin.database_browser import ConversationDatabaseBrowser
from app.config import Settings
from app.models import ModelName
from app.monitoring.events import EventLogger
from app.monitoring.log_buffer import InMemoryLogBuffer
from app.projects.registry import (
    WEBHOOK_TOKEN_HASH_PREFIX_LENGTH,
    ProjectRecord,
    ProjectRegistry,
    mask_bot_token,
)
from app.telegram.bot_instances import BotInstanceManager
from app.telegram.conversation import SQLiteConversationStore
from app.telegram.webhook_registration import TelegramWebhookRegistrar

_adminlog = EventLogger("app.admin", "admin.ui")
_monitorlog = EventLogger("app.admin.monitoring", "monitoring.ui")


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

_DEFAULT_NEW_PROJECT_WEBHOOK_SECRET = "optional-secret"


class ProjectUpsertBody(BaseModel):
    name: str
    root_path: str
    worktree_base_dir: str
    default_model: ModelName = ModelName.CLAUDE
    enabled: bool = True
    bot_token: str | None = None
    webhook_secret: str | None = None
    allowed_chat_ids: list[int] | None = None
    allowed_user_ids: list[int] | None = None


class DefaultProjectBody(BaseModel):
    name: str = Field(min_length=1)


_ADMIN_ICON_NAMES = frozenset(
    {"home.svg", "projects.svg", "advanced.svg", "logs.svg", "database.svg", "download.svg"}
)


@lru_cache(maxsize=8)
def _load_template_html(template_name: str) -> str:
    template_path = Path(__file__).parent / "templates" / template_name
    return template_path.read_text(encoding="utf-8")


def _sync_bot_instance(manager: BotInstanceManager | None, record: ProjectRecord) -> None:
    if manager is None:
        return
    if record.enabled:
        manager.register(record)
    else:
        manager.unregister(record.name)


def _sync_project_webhook(
    registrar: TelegramWebhookRegistrar | None,
    record: ProjectRecord,
) -> None:
    if registrar is None or not record.enabled:
        return
    if not registrar.sync_project(record):
        _adminlog.warning("project webhook sync failed name=%s", record.name, project=record.name)


def create_admin_router(
    settings: Settings,
    registry: ProjectRegistry,
    advanced_settings_store: FileAdvancedSettingsStore,
    log_buffer: InMemoryLogBuffer,
    conversation_store: SQLiteConversationStore,
    bot_instance_manager: BotInstanceManager | None = None,
    webhook_registrar: TelegramWebhookRegistrar | None = None,
) -> APIRouter:
    router = APIRouter(tags=["admin"])

    @router.get("/", response_class=HTMLResponse)
    def admin_hub(_: LocalhostOnly) -> str:
        _adminlog.info("page served path=/")
        return _load_template_html("admin.html")

    @router.get("/projects", response_class=HTMLResponse)
    def admin_projects(_: LocalhostOnly) -> str:
        _adminlog.info("page served path=/projects")
        return _load_template_html("projects.html")

    @router.get("/advanced", response_class=HTMLResponse)
    def admin_advanced(_: LocalhostOnly) -> str:
        _adminlog.info("page served path=/advanced")
        return _load_template_html("advanced.html")

    @router.get("/logs", response_class=HTMLResponse)
    def admin_logs(_: LocalhostOnly) -> str:
        _adminlog.info("page served path=/logs")
        return _load_template_html("logs.html")

    @router.get("/database", response_class=HTMLResponse)
    def admin_database(_: LocalhostOnly) -> str:
        _adminlog.info("page served path=/database")
        return _load_template_html("database.html")

    @router.get("/api/database/tables")
    def api_database_tables(_: LocalhostOnly) -> dict[str, object]:
        browser = ConversationDatabaseBrowser(conversation_store.db_path)
        payload = browser.tables_payload()
        _monitorlog.info("database tables queried count=%d", len(payload.get("tables", [])))
        return payload

    @router.get("/api/database/filter-options")
    def api_database_filter_options(
        _: LocalhostOnly,
        table: str = Query(..., min_length=1, max_length=64),
    ) -> dict[str, object]:
        browser = ConversationDatabaseBrowser(conversation_store.db_path)
        try:
            payload = browser.distinct_filter_options(table)
            _monitorlog.info("database filter options queried table=%s", table)
            return payload
        except ValueError as exc:
            _monitorlog.warning("database filter options failed table=%s err=%s", table, exc)
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/api/database/rows")
    def api_database_rows(
        _: LocalhostOnly,
        table: str = Query(..., min_length=1, max_length=64),
        project: str | None = Query(None, max_length=200),
        chat_id: int | None = Query(None),
        role: str | None = Query(None, max_length=64),
        job_id: str | None = Query(None, max_length=200),
        q: str | None = Query(None, max_length=500),
        sort: str | None = Query(None, max_length=64),
        order: str = Query("desc"),
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
    ) -> dict[str, object]:
        if order not in ("asc", "desc"):
            raise HTTPException(status_code=422, detail="order는 asc 또는 desc 여야 합니다.")
        browser = ConversationDatabaseBrowser(conversation_store.db_path)
        try:
            payload = browser.query_rows(
                table,
                project=project,
                chat_id=chat_id,
                role=role,
                job_id=job_id,
                q=q,
                sort=sort,
                order=order,
                limit=limit,
                offset=offset,
            )
            _monitorlog.info(
                "database rows queried table=%s rows=%d limit=%d offset=%d filters=%d",
                table,
                len(payload.get("rows", [])),
                limit,
                offset,
                sum(v is not None for v in (project, chat_id, role, job_id, q)),
                chat_id=chat_id,
                job_id=job_id,
                project=project,
            )
            return payload
        except ValueError as exc:
            _monitorlog.warning("database rows query failed table=%s err=%s", table, exc)
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/api/database/export.csv")
    def api_database_export_csv(
        _: LocalhostOnly,
        table: str = Query(..., min_length=1, max_length=64),
        project: str | None = Query(None, max_length=200),
        chat_id: int | None = Query(None),
        role: str | None = Query(None, max_length=64),
        job_id: str | None = Query(None, max_length=200),
        q: str | None = Query(None, max_length=500),
        sort: str | None = Query(None, max_length=64),
        order: str = Query("desc"),
        max_rows: int = Query(50_000, ge=1, le=100_000),
    ) -> StreamingResponse:
        if order not in ("asc", "desc"):
            raise HTTPException(status_code=422, detail="order는 asc 또는 desc 여야 합니다.")
        browser = ConversationDatabaseBrowser(conversation_store.db_path)
        try:
            stream = browser.iter_csv_rows(
                table,
                project=project,
                chat_id=chat_id,
                role=role,
                job_id=job_id,
                q=q,
                sort=sort,
                order=order,
                max_rows=max_rows,
            )
        except ValueError as exc:
            _monitorlog.warning("database export failed table=%s err=%s", table, exc)
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        safe_name = table.replace("/", "_").replace("\\", "_")[:80] or "export"
        _monitorlog.info(
            "database export started table=%s max_rows=%d filters=%d",
            table,
            max_rows,
            sum(v is not None for v in (project, chat_id, role, job_id, q)),
            chat_id=chat_id,
            job_id=job_id,
            project=project,
        )
        return StreamingResponse(
            stream,
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{safe_name}_export.csv"',
            },
        )

    @router.get("/api/logs")
    def api_logs(
        _: LocalhostOnly,
        limit: int = Query(200, ge=1, le=1000),
        after_id: int | None = Query(None, ge=1),
        level: str | None = Query(None, description="최소 로그 레벨 (DEBUG, INFO, WARNING, ERROR, CRITICAL)"),
        q: str | None = Query(None, max_length=500),
        logger: str | None = Query(None, max_length=200),
        chat_id: int | None = Query(None),
        user_id: int | None = Query(None),
        job_id: str | None = Query(None, max_length=200),
        project: str | None = Query(None, max_length=200),
        category: str | None = Query(None, max_length=64),
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
        job_id_clean = job_id.strip() if job_id else None
        if job_id_clean == "":
            job_id_clean = None
        project_clean = project.strip() if project else None
        if project_clean == "":
            project_clean = None
        category_clean = category.strip() if category else None
        if category_clean == "":
            category_clean = None
        try:
            entries, max_seen = log_buffer.query(
                limit=limit,
                after_id=after_id,
                min_level=level_clean,
                q=q_clean,
                logger_sub=logger_clean,
                chat_id=chat_id,
                user_id=user_id,
                job_id=job_id_clean,
                project=project_clean,
                category=category_clean,
            )
        except ValueError as exc:
            _monitorlog.warning("logs query failed err=%s", exc)
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        _monitorlog.info(
            "logs queried entries=%d max_id=%d after_id=%s limit=%d level=%s logger=%s category=%s",
            len(entries),
            max_seen,
            after_id or "-",
            limit,
            level_clean or "-",
            logger_clean or "-",
            category_clean or "-",
            chat_id=chat_id,
            user_id=user_id,
            job_id=job_id_clean,
            project=project_clean,
        )
        return {
            "entries": entries,
            "max_id": max_seen,
            "max_entries": log_buffer.max_entries,
        }

    @router.get("/api/settings")
    def api_settings(_: LocalhostOnly) -> dict:
        token = (
            settings.telegram_bot_token.get_secret_value()
            if settings.telegram_bot_token is not None
            else ""
        )
        _adminlog.info(
            "settings queried env_allowlist_chats=%d env_allowlist_users=%d webhook_secret_set=%s default_model=%s",
            len(settings.telegram_allowed_chat_ids),
            len(settings.telegram_allowed_user_ids),
            bool(settings.telegram_webhook_secret),
            settings.default_model.value,
        )
        return {
            "telegram_bot_token_masked": mask_bot_token(token),
            "telegram_allowed_chat_ids": settings.telegram_allowed_chat_ids,
            "telegram_allowed_user_ids": settings.telegram_allowed_user_ids,
            "telegram_webhook_secret_set": bool(settings.telegram_webhook_secret),
            "default_model_env": settings.default_model.value,
            "job_timeout_seconds_env": settings.job_timeout_seconds,
            "projects_config_path": str(registry.config_path),
            "webhook_token_hash_prefix_length": WEBHOOK_TOKEN_HASH_PREFIX_LENGTH,
            "webhook_route_template": "/telegram/webhook/{token_hash_prefix}",
            "webhook_public_url_rule": "<공개 HTTPS Base URL> + 각 프로젝트의 webhook_path",
            "webhook_hint": "각 프로젝트(봇)마다 webhook_path·token_hash_prefix가 다릅니다. "
            "전체 URL은 공개 Base에 webhook_path를 이어붙입니다. ./run.sh 실행 중에는 등록·수정 시 자동 갱신됩니다. "
            "수동 등록: python scripts/set_webhook.py <Base URL>",
            "webhook_deleted_disabled_note": (
                "프로젝트를 비활성화하거나 삭제하면 서버는 해당 token_hash_prefix로 들어오는 업데이트를 "
                "더 이상 처리하지 않습니다(매칭 실패·404). Telegram이 예전 URL로 호출을 보내도 이 앱에서는 "
                "무시됩니다. 봇의 webhook을 비우거나 새 URL로 맞추려면 Bot API deleteWebhook 또는 "
                "갱신된 레지스트리로 scripts/set_webhook.py 를 다시 실행하세요."
            ),
        }

    @router.get("/api/projects")
    def api_projects_get(_: LocalhostOnly) -> JSONResponse:
        _adminlog.info("projects queried count=%d", len(registry.list_projects()))
        return JSONResponse(registry.to_public_dict())

    @router.post("/api/projects")
    def api_projects_create(body: ProjectUpsertBody, _: LocalhostOnly) -> JSONResponse:
        if not body.bot_token or not body.bot_token.strip():
            raise HTTPException(status_code=400, detail="bot_token is required")
        if not body.allowed_chat_ids:
            raise HTTPException(status_code=400, detail="allowed_chat_ids must have at least one entry")
        wh_stripped = (body.webhook_secret or "").strip()
        webhook_secret = SecretStr(
            wh_stripped if wh_stripped else _DEFAULT_NEW_PROJECT_WEBHOOK_SECRET
        )
        record = ProjectRecord(
            name=body.name,
            root_path=body.root_path,
            worktree_base_dir=body.worktree_base_dir,
            default_model=body.default_model,
            enabled=body.enabled,
            bot_token=SecretStr(body.bot_token.strip()),
            webhook_secret=webhook_secret,
            allowed_chat_ids=list(body.allowed_chat_ids),
            allowed_user_ids=list(body.allowed_user_ids or []),
        )
        try:
            registry.add_project(record)
        except ValueError as exc:
            _adminlog.warning("project create failed name=%s err=%s", body.name, exc, project=body.name)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        _adminlog.info("project created name=%s enabled=%s", body.name, body.enabled, project=body.name)
        _sync_bot_instance(bot_instance_manager, record)
        _sync_project_webhook(webhook_registrar, record)
        return JSONResponse(registry.to_public_dict())

    @router.put("/api/projects/{name}")
    def api_projects_update(name: str, body: ProjectUpsertBody, _: LocalhostOnly) -> JSONResponse:
        existing = registry.get(name)
        if existing is None:
            raise HTTPException(status_code=404, detail=f"unknown project: {name}")
        bot_token = (
            SecretStr(body.bot_token.strip())
            if body.bot_token and body.bot_token.strip()
            else existing.bot_token
        )
        if body.webhook_secret is not None:
            webhook_secret = SecretStr(body.webhook_secret) if body.webhook_secret.strip() else None
        else:
            webhook_secret = existing.webhook_secret
        allowed_chat_ids = (
            list(body.allowed_chat_ids)
            if body.allowed_chat_ids is not None
            else existing.allowed_chat_ids
        )
        if not allowed_chat_ids:
            raise HTTPException(status_code=400, detail="allowed_chat_ids must have at least one entry")
        allowed_user_ids = (
            list(body.allowed_user_ids)
            if body.allowed_user_ids is not None
            else existing.allowed_user_ids
        )
        record = ProjectRecord(
            name=body.name,
            root_path=body.root_path,
            worktree_base_dir=body.worktree_base_dir,
            default_model=body.default_model,
            enabled=body.enabled,
            bot_token=bot_token,
            webhook_secret=webhook_secret,
            allowed_chat_ids=allowed_chat_ids,
            allowed_user_ids=allowed_user_ids,
        )
        try:
            registry.update_project(name, record)
        except ValueError as exc:
            _adminlog.warning(
                "project update failed old_name=%s new_name=%s err=%s",
                name,
                body.name,
                exc,
                project=name,
            )
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        _adminlog.info(
            "project updated old_name=%s new_name=%s enabled=%s",
            name,
            body.name,
            body.enabled,
            project=body.name,
        )
        _sync_bot_instance(bot_instance_manager, record)
        _sync_project_webhook(webhook_registrar, record)
        return JSONResponse(registry.to_public_dict())

    @router.delete("/api/projects/{name}")
    def api_projects_delete(name: str, _: LocalhostOnly) -> JSONResponse:
        try:
            registry.remove_project(name)
        except ValueError as exc:
            _adminlog.warning("project delete failed name=%s err=%s", name, exc, project=name)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        _adminlog.info("project deleted name=%s", name, project=name)
        if bot_instance_manager is not None:
            bot_instance_manager.unregister(name)
        return JSONResponse(registry.to_public_dict())

    @router.post("/api/projects/default")
    def api_projects_set_default(body: DefaultProjectBody, _: LocalhostOnly) -> JSONResponse:
        try:
            registry.set_default_project(body.name)
        except ValueError as exc:
            _adminlog.warning("default project update failed name=%s err=%s", body.name, exc, project=body.name)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        _adminlog.info("default project updated name=%s", body.name, project=body.name)
        return JSONResponse(registry.to_public_dict())

    @router.get("/api/advanced-settings")
    def api_advanced_settings_get(_: LocalhostOnly) -> dict:
        _adminlog.info("advanced settings queried")
        return advanced_settings_store.get().model_dump(mode="json")

    @router.put("/api/advanced-settings")
    def api_advanced_settings_put(body: AdvancedSettings, _: LocalhostOnly) -> dict:
        saved = advanced_settings_store.save(body)
        _adminlog.info(
            "advanced settings updated auto_merge=%s delete_rebased_branch=%s natural_confirm_buttons=%s status_limit=%d job_timeout=%s memory_limit=%s",
            saved.auto_merge_to_main_enabled,
            saved.delete_rebased_branch_enabled,
            saved.natural_job_confirmation_buttons_enabled,
            saved.status_recent_job_limit,
            saved.job_timeout_seconds or "-",
            saved.conversation_memory_limit_enabled,
        )
        return saved.model_dump(mode="json")

    @router.get("/admin-static/icons/{filename}")
    def admin_icon(filename: str, _: LocalhostOnly) -> FileResponse:
        if filename not in _ADMIN_ICON_NAMES:
            raise HTTPException(status_code=404, detail="not found")
        path = Path(__file__).parent / "static" / "icons" / filename
        if not path.is_file():
            raise HTTPException(status_code=404, detail="not found")
        return FileResponse(path, media_type="image/svg+xml")

    return router
