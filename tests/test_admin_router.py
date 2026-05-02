from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.admin.router import create_admin_router
from app.models import ModelName
from app.projects.registry import ProjectRecord


def test_admin_root_returns_html(test_settings, project_registry, advanced_settings_store):
    app = FastAPI()
    app.include_router(create_admin_router(test_settings, project_registry, advanced_settings_store))
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert "Remote AI Coder" in response.text


def test_admin_api_settings_masks_short_token(test_settings, project_registry, advanced_settings_store):
    app = FastAPI()
    app.include_router(create_admin_router(test_settings, project_registry, advanced_settings_store))
    client = TestClient(app)
    response = client.get("/api/settings")
    assert response.status_code == 200
    data = response.json()
    assert data["telegram_bot_token_masked"] == "***"


def test_admin_api_projects_post_and_delete(test_settings, project_registry, advanced_settings_store):
    app = FastAPI()
    app.include_router(create_admin_router(test_settings, project_registry, advanced_settings_store))
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
        },
    )
    assert response.status_code == 200
    names = [p["name"] for p in response.json()["projects"]]
    assert "extra" in names

    del_r = client.delete("/api/projects/extra")
    assert del_r.status_code == 200
    names_after = [p["name"] for p in del_r.json()["projects"]]
    assert "extra" not in names_after


def test_admin_api_projects_put_updates(test_settings, project_registry, advanced_settings_store):
    app = FastAPI()
    app.include_router(create_admin_router(test_settings, project_registry, advanced_settings_store))
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
        },
    )
    assert response.status_code == 200
    updated = next(p for p in response.json()["projects"] if p["name"] == "remote-coder")
    assert updated["default_model"] == "codex"

    project_registry.update_project(
        "remote-coder",
        ProjectRecord(
            name="remote-coder",
            root_path=entry.root_path,
            worktree_base_dir=entry.worktree_base_dir,
            default_model=ModelName.CLAUDE,
            enabled=True,
        ),
    )


def test_admin_api_advanced_settings_get_default(test_settings, project_registry, advanced_settings_store):
    app = FastAPI()
    app.include_router(create_admin_router(test_settings, project_registry, advanced_settings_store))
    client = TestClient(app)
    r = client.get("/api/advanced-settings")
    assert r.status_code == 200
    data = r.json()
    assert data["auto_merge_to_main_enabled"] is False
    assert data["conversation_memory_limit_enabled"] is False


def test_admin_api_advanced_settings_put_and_persist(test_settings, project_registry, advanced_settings_store):
    app = FastAPI()
    app.include_router(create_admin_router(test_settings, project_registry, advanced_settings_store))
    client = TestClient(app)
    body = {
        "auto_merge_to_main_enabled": True,
        "conversation_memory_limit_enabled": True,
        "conversation_memory_max_rows": 100,
        "conversation_memory_max_bytes": None,
    }
    put = client.put("/api/advanced-settings", json=body)
    assert put.status_code == 200
    assert put.json()["auto_merge_to_main_enabled"] is True
    get = client.get("/api/advanced-settings")
    assert get.json()["conversation_memory_max_rows"] == 100


def test_admin_api_advanced_settings_put_invalid_memory_returns_422(
    test_settings, project_registry, advanced_settings_store
):
    app = FastAPI()
    app.include_router(create_admin_router(test_settings, project_registry, advanced_settings_store))
    client = TestClient(app)
    r = client.put(
        "/api/advanced-settings",
        json={
            "auto_merge_to_main_enabled": False,
            "conversation_memory_limit_enabled": True,
            "conversation_memory_max_rows": None,
            "conversation_memory_max_bytes": None,
        },
    )
    assert r.status_code == 422
