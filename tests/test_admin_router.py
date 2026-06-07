import re
from pathlib import Path
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import app.admin.router as admin_router_module
from app.admin.advanced_settings import AdvancedSettings
from app.admin.database_browser import _TABLES
from app.admin.router import create_admin_router
from app.models import ModelName, UiLanguage

_ADMIN_DIR = Path(admin_router_module.__file__).parent
_I18N_JS = (_ADMIN_DIR / "static" / "i18n.js").read_text(encoding="utf-8")
_CATALOG_KEYS = set(re.findall(r'"([A-Za-z0-9_.]+)":\s*\{\s*en:', _I18N_JS))


def _referenced_i18n_keys() -> set[str]:
    keys: set[str] = set()
    sources = list((_ADMIN_DIR / "templates").glob("*.html"))
    sources.append(_ADMIN_DIR / "static" / "summary.js")
    for source in sources:
        text = source.read_text(encoding="utf-8")
        keys |= set(re.findall(r'data-i18n(?:-[a-z-]+)?="([^"]+)"', text))
        keys |= set(re.findall(r'i18n\.t\("([^"]+)"', text))
    return keys


def test_admin_root_returns_html(test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store):
    app = FastAPI()
    app.include_router(create_admin_router(
        test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store
    ))
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert "Remote AI Coder" in response.text
    assert 'href="/projects"' in response.text
    assert 'href="/advanced"' in response.text
    assert 'href="/logs"' in response.text
    assert 'href="/database"' in response.text
    assert "Projects" in response.text
    assert "Advanced settings" in response.text
    assert 'window.__UI_LANG__="en"' in response.text
    assert 'id="proj-form"' not in response.text
    assert 'id="adv-form"' not in response.text
    assert 'id="active-projects-view"' in response.text
    assert 'id="summary-grid"' in response.text
    assert 'id="setup-section"' in response.text
    assert "/admin-static/i18n.js" in response.text
    assert "/admin-static/summary.js" in response.text


def test_admin_projects_page_returns_html(test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store):
    app = FastAPI()
    app.include_router(create_admin_router(
        test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store
    ))
    client = TestClient(app)
    response = client.get("/projects")
    assert response.status_code == 200
    assert "Project registration" in response.text
    assert 'id="proj-form"' in response.text
    assert 'href="/"' in response.text
    assert 'href="/advanced"' in response.text
    assert "Telegram webhook (멀티봇)" not in response.text
    assert "webhook-base-preview" not in response.text
    assert 'class="optional-fields"' in response.text
    assert "Optional fields" in response.text
    assert 'id="f-wh-secret"' in response.text
    assert 'id="f-users"' in response.text


def test_admin_advanced_page_returns_html(test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store):
    app = FastAPI()
    app.include_router(create_admin_router(
        test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store
    ))
    client = TestClient(app)
    response = client.get("/advanced")
    assert response.status_code == 200
    assert "Advanced Settings" in response.text
    assert 'id="adv-form"' in response.text
    assert 'id="adv-job-timeout"' in response.text
    assert 'href="/"' in response.text
    assert 'href="/projects"' in response.text


def test_admin_icon_svg_served_for_localhost(test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store):
    app = FastAPI()
    app.include_router(create_admin_router(
        test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store
    ))
    client = TestClient(app)
    r = client.get("/admin-static/icons/projects.svg")
    assert r.status_code == 200
    assert "image/svg+xml" in (r.headers.get("content-type") or "")
    assert b"<svg" in r.content

    bad = client.get("/admin-static/icons/other.svg")
    assert bad.status_code == 404


def test_admin_api_settings_masks_short_token(test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store):
    app = FastAPI()
    app.include_router(create_admin_router(
        test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store
    ))
    client = TestClient(app)
    response = client.get("/api/settings")
    assert response.status_code == 200
    data = response.json()
    assert data["telegram_bot_token_masked"] == "***"


def test_admin_api_settings_includes_webhook_operations_metadata(
    test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store
):
    app = FastAPI()
    app.include_router(
        create_admin_router(
            test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store
        )
    )
    client = TestClient(app)
    data = client.get("/api/settings").json()
    assert data["webhook_token_hash_prefix_length"] == 16
    assert data["webhook_route_template"] == "/telegram/webhook/{token_hash_prefix}"
    assert data["webhook_public_url_rule"]
    assert data["webhook_deleted_disabled_note"]


def test_admin_api_projects_post_and_delete(test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store):
    app = FastAPI()
    app.include_router(create_admin_router(
        test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store
    ))
    client = TestClient(app)

    root = test_settings.project_root / "new_repo"
    root.mkdir()
    wt = test_settings.project_root / "new_wt"
    wt.mkdir()

    response = client.post(
        "/api/projects",
        json={
            "name": "extra",
            "root_path": str(root),
            "worktree_base_dir": str(wt),
            "default_model": "codex",
            "enabled": True,
            "bot_token": "123456:ABC-extra-bot",
            "allowed_chat_ids": [123],
            "allowed_user_ids": [],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    names = [p["name"] for p in payload["projects"]]
    assert "extra" in names
    extra = next(p for p in payload["projects"] if p["name"] == "extra")
    assert extra["webhook_path"].startswith("/telegram/webhook/")
    assert len(extra["token_hash_prefix"]) == 16
    assert extra["webhook_secret_set"] is True
    stored = project_registry.get("extra")
    assert stored is not None
    assert stored.webhook_secret is not None
    assert stored.webhook_secret.get_secret_value() == "optional-secret"

    del_r = client.delete("/api/projects/extra")
    assert del_r.status_code == 200
    names_after = [p["name"] for p in del_r.json()["projects"]]
    assert "extra" not in names_after


def test_admin_api_projects_syncs_bot_instance_manager(
    test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store
):
    bot_mgr = MagicMock()
    webhook_registrar = MagicMock()
    webhook_registrar.sync_project.return_value = True
    app = FastAPI()
    app.include_router(
        create_admin_router(
            test_settings,
            project_registry,
            advanced_settings_store,
            log_buffer,
            conversation_store,
            bot_instance_manager=bot_mgr,
            webhook_registrar=webhook_registrar,
        )
    )
    client = TestClient(app)

    root = test_settings.project_root / "bim_repo"
    root.mkdir()
    wt = test_settings.project_root / "bim_wt"
    wt.mkdir()

    client.post(
        "/api/projects",
        json={
            "name": "bimproj",
            "root_path": str(root),
            "worktree_base_dir": str(wt),
            "default_model": "claude",
            "enabled": True,
            "bot_token": "888888:AA-bim-bot-test",
            "allowed_chat_ids": [9],
            "allowed_user_ids": [],
        },
    )
    bot_mgr.register.assert_called()
    reg_arg = bot_mgr.register.call_args[0][0]
    assert reg_arg.name == "bimproj"
    assert reg_arg.webhook_secret is not None
    assert reg_arg.webhook_secret.get_secret_value() == "optional-secret"
    webhook_registrar.sync_project.assert_called_once()
    wh_arg = webhook_registrar.sync_project.call_args[0][0]
    assert wh_arg.name == "bimproj"

    bot_mgr.reset_mock()
    webhook_registrar.reset_mock()
    client.put(
        "/api/projects/bimproj",
        json={
            "name": "bimproj",
            "root_path": str(root),
            "worktree_base_dir": str(wt),
            "default_model": "claude",
            "enabled": False,
            "allowed_chat_ids": [9],
            "allowed_user_ids": [],
        },
    )
    bot_mgr.unregister.assert_called_once_with("bimproj")
    webhook_registrar.sync_project.assert_not_called()

    bot_mgr.reset_mock()
    webhook_registrar.reset_mock()
    client.put(
        "/api/projects/bimproj",
        json={
            "name": "bimproj",
            "root_path": str(root),
            "worktree_base_dir": str(wt),
            "default_model": "claude",
            "enabled": True,
            "allowed_chat_ids": [9],
            "allowed_user_ids": [],
        },
    )
    bot_mgr.register.assert_called_once()
    webhook_registrar.sync_project.assert_called_once()

    bot_mgr.reset_mock()
    webhook_registrar.reset_mock()
    client.delete("/api/projects/bimproj")
    bot_mgr.unregister.assert_called_once_with("bimproj")
    webhook_registrar.sync_project.assert_not_called()


def test_admin_api_projects_put_omitted_webhook_secret_preserves(
    test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store
):
    app = FastAPI()
    app.include_router(
        create_admin_router(
            test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store
        )
    )
    client = TestClient(app)

    root = test_settings.project_root / "wh_omit_repo"
    root.mkdir()
    wt = test_settings.project_root / "wh_omit_wt"
    wt.mkdir()

    create = client.post(
        "/api/projects",
        json={
            "name": "wh-omit",
            "root_path": str(root),
            "worktree_base_dir": str(wt),
            "default_model": "claude",
            "enabled": True,
            "bot_token": "777777:AA-wh-omit-bot",
            "webhook_secret": "persist-wh-secret",
            "allowed_chat_ids": [3],
            "allowed_user_ids": [],
        },
    )
    assert create.status_code == 200

    res = client.put(
        "/api/projects/wh-omit",
        json={
            "name": "wh-omit",
            "root_path": str(root),
            "worktree_base_dir": str(wt),
            "default_model": "claude",
            "enabled": True,
            "allowed_chat_ids": [3],
            "allowed_user_ids": [],
        },
    )
    assert res.status_code == 200
    updated = project_registry.get("wh-omit")
    assert updated is not None
    assert updated.webhook_secret is not None
    assert updated.webhook_secret.get_secret_value() == "persist-wh-secret"

    client.delete("/api/projects/wh-omit")


def test_admin_api_projects_put_empty_webhook_secret_clears(
    test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store
):
    app = FastAPI()
    app.include_router(
        create_admin_router(
            test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store
        )
    )
    client = TestClient(app)

    root = test_settings.project_root / "wh_clear_repo"
    root.mkdir()
    wt = test_settings.project_root / "wh_clear_wt"
    wt.mkdir()

    create = client.post(
        "/api/projects",
        json={
            "name": "wh-clear",
            "root_path": str(root),
            "worktree_base_dir": str(wt),
            "default_model": "claude",
            "enabled": True,
            "bot_token": "666666:AA-wh-clear-bot",
            "webhook_secret": "to-clear",
            "allowed_chat_ids": [4],
            "allowed_user_ids": [],
        },
    )
    assert create.status_code == 200

    res = client.put(
        "/api/projects/wh-clear",
        json={
            "name": "wh-clear",
            "root_path": str(root),
            "worktree_base_dir": str(wt),
            "default_model": "claude",
            "enabled": True,
            "allowed_chat_ids": [4],
            "allowed_user_ids": [],
            "webhook_secret": "",
        },
    )
    assert res.status_code == 200
    updated = project_registry.get("wh-clear")
    assert updated is not None
    assert updated.webhook_secret is None

    client.delete("/api/projects/wh-clear")


def test_admin_api_projects_put_updates(test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store):
    app = FastAPI()
    app.include_router(create_admin_router(
        test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store
    ))
    client = TestClient(app)

    entry = project_registry.get("remote-coder")
    assert entry is not None
    response = client.put(
        "/api/projects/remote-coder",
        json={
            "name": "remote-coder",
            "root_path": str(entry.root_path),
            "worktree_base_dir": str(entry.worktree_base_dir),
            "default_model": "codex",
            "enabled": True,
            "allowed_chat_ids": entry.allowed_chat_ids,
            "allowed_user_ids": entry.allowed_user_ids,
        },
    )
    assert response.status_code == 200
    updated = next(p for p in response.json()["projects"] if p["name"] == "remote-coder")
    assert updated["default_model"] == "codex"

    current = project_registry.get("remote-coder")
    assert current is not None
    project_registry.update_project(
        "remote-coder",
        current.model_copy(update={"default_model": ModelName.CLAUDE}),
    )


def test_admin_api_advanced_settings_get_default(test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store):
    app = FastAPI()
    app.include_router(create_admin_router(
        test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store
    ))
    client = TestClient(app)
    r = client.get("/api/advanced-settings")
    assert r.status_code == 200
    data = r.json()
    assert data["ui_language"] == "en"
    assert data["server_lifecycle_notify_enabled"] is True
    assert data["pull_projects_on_server_startup_enabled"] is False
    assert data["auto_merge_to_main_enabled"] is False
    assert data["delete_rebased_branch_enabled"] is True
    assert data["natural_job_confirmation_buttons_enabled"] is False
    assert data["conversation_memory_limit_enabled"] is False
    assert data["job_timeout_seconds"] is None


def test_admin_api_advanced_settings_put_and_persist(test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store):
    app = FastAPI()
    app.include_router(create_admin_router(
        test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store
    ))
    client = TestClient(app)
    body = {
        "ui_language": "en",
        "server_lifecycle_notify_enabled": False,
        "pull_projects_on_server_startup_enabled": True,
        "auto_merge_to_main_enabled": True,
        "delete_rebased_branch_enabled": False,
        "natural_job_confirmation_buttons_enabled": True,
        "conversation_memory_limit_enabled": True,
        "conversation_memory_max_rows": 100,
        "conversation_memory_max_bytes": None,
        "status_recent_job_limit": 7,
        "job_timeout_seconds": 3600,
    }
    put = client.put("/api/advanced-settings", json=body)
    assert put.status_code == 200
    assert put.json()["server_lifecycle_notify_enabled"] is False
    assert put.json()["pull_projects_on_server_startup_enabled"] is True
    assert put.json()["auto_merge_to_main_enabled"] is True
    assert put.json()["delete_rebased_branch_enabled"] is False
    assert put.json()["natural_job_confirmation_buttons_enabled"] is True
    assert put.json()["job_timeout_seconds"] == 3600
    get = client.get("/api/advanced-settings")
    assert get.json()["server_lifecycle_notify_enabled"] is False
    assert get.json()["pull_projects_on_server_startup_enabled"] is True
    assert get.json()["conversation_memory_max_rows"] == 100
    assert get.json()["delete_rebased_branch_enabled"] is False
    assert get.json()["natural_job_confirmation_buttons_enabled"] is True
    assert get.json()["status_recent_job_limit"] == 7


def test_admin_api_advanced_settings_put_invalid_memory_returns_422(
    test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store
):
    app = FastAPI()
    app.include_router(create_admin_router(
        test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store
    ))
    client = TestClient(app)
    r = client.put(
        "/api/advanced-settings",
        json={
            "auto_merge_to_main_enabled": False,
            "delete_rebased_branch_enabled": True,
            "natural_job_confirmation_buttons_enabled": False,
            "conversation_memory_limit_enabled": True,
            "conversation_memory_max_rows": None,
            "conversation_memory_max_bytes": None,
        },
    )
    assert r.status_code == 422


def test_admin_logs_page_returns_html(test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store):
    app = FastAPI()
    app.include_router(create_admin_router(
        test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store
    ))
    client = TestClient(app)
    response = client.get("/logs")
    assert response.status_code == 200
    assert "Server logs" in response.text
    assert 'id="console"' in response.text
    assert 'id="f-category"' in response.text
    assert 'id="f-job-id"' in response.text


def test_admin_api_logs_returns_json(test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store):
    log_buffer.push(level="INFO", logger_name="app.test", message="hello", exception=None)
    app = FastAPI()
    app.include_router(create_admin_router(
        test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store
    ))
    client = TestClient(app)
    r = client.get("/api/logs")
    assert r.status_code == 200
    data = r.json()
    assert "entries" in data
    assert "max_id" in data
    assert data["max_entries"] == 500
    assert len(data["entries"]) >= 1
    assert data["entries"][-1]["message"] == "hello"
    entry = data["entries"][-1]
    assert "category" in entry
    assert "chat_id" in entry
    assert "job_id" in entry
    assert "project" in entry
    assert "user_id" in entry


def test_admin_api_logs_filters_by_chat_job_category(
    test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store
):
    log_buffer.push(
        level="INFO",
        logger_name="app.jobs",
        message="a",
        exception=None,
        context={"chat_id": 123, "job_id": "job_x", "category": "job.lifecycle", "project": "p1"},
    )
    log_buffer.push(
        level="INFO",
        logger_name="app.jobs",
        message="b",
        exception=None,
        context={"chat_id": 999, "job_id": "other", "category": "job.lifecycle"},
    )
    app = FastAPI()
    app.include_router(
        create_admin_router(
            test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store
        )
    )
    client = TestClient(app)
    r1 = client.get("/api/logs?chat_id=123")
    assert r1.status_code == 200
    assert len(r1.json()["entries"]) == 1
    assert r1.json()["entries"][0]["message"] == "a"

    r2 = client.get("/api/logs?job_id=job_x")
    assert r2.status_code == 200
    assert len(r2.json()["entries"]) == 1

    r3 = client.get("/api/logs?category=job.lifecycle")
    assert r3.status_code == 200
    assert len(r3.json()["entries"]) == 2


def test_admin_api_logs_unknown_level_returns_422(test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store):
    app = FastAPI()
    app.include_router(create_admin_router(
        test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store
    ))
    client = TestClient(app)
    r = client.get("/api/logs?level=VERBOSE")
    assert r.status_code == 422


def test_admin_logs_icon_served(test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store):
    app = FastAPI()
    app.include_router(create_admin_router(
        test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store
    ))
    client = TestClient(app)
    r = client.get("/admin-static/icons/logs.svg")
    assert r.status_code == 200
    assert b"<svg" in r.content


def test_admin_api_logs_after_id(test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store):
    log_buffer.push(level="DEBUG", logger_name="a", message="one", exception=None)
    log_buffer.push(level="INFO", logger_name="b", message="two", exception=None)
    app = FastAPI()
    app.include_router(create_admin_router(
        test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store
    ))
    client = TestClient(app)
    first = client.get("/api/logs?limit=10")
    mid = first.json()["entries"][0]["id"]
    tail = client.get(f"/api/logs?after_id={mid}&limit=10")
    assert tail.status_code == 200
    ids = [e["id"] for e in tail.json()["entries"]]
    assert all(i > mid for i in ids)


def test_admin_database_page_returns_html(
    test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store
):
    app = FastAPI()
    app.include_router(
        create_admin_router(
            test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store
        )
    )
    client = TestClient(app)
    response = client.get("/database")
    assert response.status_code == 200
    assert "Data browser" in response.text
    assert 'id="data-table"' in response.text
    assert 'id="text-detail-modal"' in response.text
    assert "btn-detail" in response.text
    assert 'id="btn-csv"' in response.text


def test_admin_api_database_filter_options(
    test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store
):
    conversation_store.append(project="fp", chat_id=1, role="user", text="x", job_id=None)
    conversation_store.append(project="fp", chat_id=1, role="job_result", text="y", job_id="j")
    app = FastAPI()
    app.include_router(
        create_admin_router(
            test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store
        )
    )
    client = TestClient(app)
    r = client.get("/api/database/filter-options?table=conversation_entries")
    assert r.status_code == 200
    data = r.json()
    assert "fp" in data["projects"]
    assert "user" in data["roles"]
    assert "job_result" in data["roles"]

    r2 = client.get("/api/database/filter-options?table=message_branch_links")
    assert r2.status_code == 200
    assert r2.json()["roles"] == []


def test_admin_api_database_tables(
    test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store
):
    app = FastAPI()
    app.include_router(
        create_admin_router(
            test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store
        )
    )
    client = TestClient(app)
    r = client.get("/api/database/tables")
    assert r.status_code == 200
    data = r.json()
    assert data["db_exists"] is True
    names = {t["name"] for t in data["tables"]}
    assert "conversation_entries" in names
    assert "message_branch_links" in names


def test_admin_api_database_rows_filters(
    test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store
):
    conversation_store.append(project="p1", chat_id=99, role="user", text="hello filter", job_id=None)
    app = FastAPI()
    app.include_router(
        create_admin_router(
            test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store
        )
    )
    client = TestClient(app)
    r = client.get("/api/database/rows?table=conversation_entries&project=p1&role=user&q=filter")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] >= 1
    assert any(row.get("text") == "hello filter" for row in data["rows"])


def test_admin_api_database_unknown_table_returns_422(
    test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store
):
    app = FastAPI()
    app.include_router(
        create_admin_router(
            test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store
        )
    )
    client = TestClient(app)
    r = client.get("/api/database/rows?table=sqlite_master")
    assert r.status_code == 422


def test_admin_api_database_invalid_sort_returns_422(
    test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store
):
    app = FastAPI()
    app.include_router(
        create_admin_router(
            test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store
        )
    )
    client = TestClient(app)
    r = client.get("/api/database/rows?table=conversation_entries&sort=evil")
    assert r.status_code == 422


def test_admin_api_database_invalid_order_returns_422(
    test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store
):
    app = FastAPI()
    app.include_router(
        create_admin_router(
            test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store
        )
    )
    client = TestClient(app)
    r = client.get("/api/database/rows?table=conversation_entries&order=down")
    assert r.status_code == 422


def test_admin_database_icon_served(
    test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store
):
    app = FastAPI()
    app.include_router(
        create_admin_router(
            test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store
        )
    )
    client = TestClient(app)
    r = client.get("/admin-static/icons/database.svg")
    assert r.status_code == 200
    assert b"<svg" in r.content


def test_admin_download_icon_served(
    test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store
):
    app = FastAPI()
    app.include_router(
        create_admin_router(
            test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store
        )
    )
    client = TestClient(app)
    r = client.get("/admin-static/icons/download.svg")
    assert r.status_code == 200
    assert b"<svg" in r.content


def test_admin_api_database_export_csv(
    test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store
):
    conversation_store.append(project="csv_p", chat_id=1, role="user", text="line,with\"comma", job_id=None)
    app = FastAPI()
    app.include_router(
        create_admin_router(
            test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store
        )
    )
    client = TestClient(app)
    r = client.get("/api/database/export.csv?table=conversation_entries&project=csv_p&sort=id&order=desc")
    assert r.status_code == 200
    ct = r.headers.get("content-type", "")
    assert "text/csv" in ct
    assert "attachment" in (r.headers.get("content-disposition") or "").lower()
    body = r.content.decode("utf-8")
    assert body.startswith("\ufeff")
    assert "id,project" in body.split("\n")[0]
    assert "csv_p" in body


def test_admin_i18n_js_served(
    test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store
):
    app = FastAPI()
    app.include_router(
        create_admin_router(
            test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store
        )
    )
    client = TestClient(app)
    r = client.get("/admin-static/i18n.js")
    assert r.status_code == 200
    assert "javascript" in (r.headers.get("content-type") or "")
    assert "window.i18n" in r.text


def test_admin_pages_default_to_english(
    test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store
):
    app = FastAPI()
    app.include_router(
        create_admin_router(
            test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store
        )
    )
    client = TestClient(app)
    for path in ("/", "/projects", "/advanced", "/logs", "/database"):
        r = client.get(path)
        assert r.status_code == 200
        assert 'window.__UI_LANG__="en"' in r.text


def test_admin_pages_inject_korean_when_selected(
    test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store
):
    advanced_settings_store.save(AdvancedSettings(ui_language=UiLanguage.KOREAN))
    app = FastAPI()
    app.include_router(
        create_admin_router(
            test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store
        )
    )
    client = TestClient(app)
    r = client.get("/")
    assert 'window.__UI_LANG__="ko"' in r.text
    # English stays canonical in the DOM; Korean is applied client-side from the catalog.
    assert "Active projects" in r.text
    advanced_settings_store.save(AdvancedSettings(ui_language=UiLanguage.ENGLISH))


def test_api_prerequisites_returns_report(
    test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store, monkeypatch
):
    from app.diagnostics import AiCliStatus, PrerequisitesReport

    report = PrerequisitesReport(
        ngrok_ok=True,
        ngrok_detail="",
        ai_clis=[
            AiCliStatus(name="claude", installed=True),
            AiCliStatus(name="codex", installed=False),
            AiCliStatus(name="gemini", installed=False),
        ],
    )
    monkeypatch.setattr(admin_router_module, "check_prerequisites", lambda: report)

    app = FastAPI()
    app.include_router(create_admin_router(
        test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store
    ))
    client = TestClient(app)

    response = client.get("/api/prerequisites")
    assert response.status_code == 200
    body = response.json()
    assert body["ngrok_ok"] is True
    assert {c["name"]: c["installed"] for c in body["ai_clis"]} == {
        "claude": True,
        "codex": False,
        "gemini": False,
    }


def test_admin_i18n_referenced_keys_exist_in_catalog():
    missing = _referenced_i18n_keys() - _CATALOG_KEYS
    assert not missing, f"i18n keys referenced but missing from catalog: {sorted(missing)}"


def test_admin_i18n_catalog_entries_have_english():
    entries = re.findall(r'"[A-Za-z0-9_.]+":\s*\{\s*en:\s*("(?:[^"\\]|\\.)*")', _I18N_JS)
    assert entries
    assert all(len(en) > 2 for en in entries)


def test_admin_i18n_covers_backend_supplied_values():
    # tv() resolves backend English values via reverse lookup, so they must be catalog en values.
    backend_values = {spec.label for spec in _TABLES.values()}
    backend_values.add("(not set)")
    catalog_en = set(re.findall(r'en:\s*"((?:[^"\\]|\\.)*)"', _I18N_JS))
    assert backend_values <= catalog_en, f"untranslatable backend values: {backend_values - catalog_en}"
