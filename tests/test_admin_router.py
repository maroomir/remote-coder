from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.admin.router import create_admin_router
from app.models import ModelName
from app.projects.registry import ProjectRecord


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
    assert "프로젝트 등록" in response.text
    assert "고급 설정" in response.text
    assert 'id="proj-form"' not in response.text
    assert 'id="adv-form"' not in response.text
    assert 'id="active-projects-view"' in response.text
    assert "활성 프로젝트" in response.text


def test_admin_projects_page_returns_html(test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store):
    app = FastAPI()
    app.include_router(create_admin_router(
        test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store
    ))
    client = TestClient(app)
    response = client.get("/projects")
    assert response.status_code == 200
    assert "프로젝트 등록" in response.text
    assert 'id="proj-form"' in response.text
    assert 'href="/"' in response.text
    assert 'href="/advanced"' in response.text


def test_admin_advanced_page_returns_html(test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store):
    app = FastAPI()
    app.include_router(create_admin_router(
        test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store
    ))
    client = TestClient(app)
    response = client.get("/advanced")
    assert response.status_code == 200
    assert "고급 설정" in response.text
    assert 'id="adv-form"' in response.text
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
        },
    )
    assert response.status_code == 200
    names = [p["name"] for p in response.json()["projects"]]
    assert "extra" in names

    del_r = client.delete("/api/projects/extra")
    assert del_r.status_code == 200
    names_after = [p["name"] for p in del_r.json()["projects"]]
    assert "extra" not in names_after


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


def test_admin_api_advanced_settings_get_default(test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store):
    app = FastAPI()
    app.include_router(create_admin_router(
        test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store
    ))
    client = TestClient(app)
    r = client.get("/api/advanced-settings")
    assert r.status_code == 200
    data = r.json()
    assert data["auto_merge_to_main_enabled"] is False
    assert data["conversation_memory_limit_enabled"] is False


def test_admin_api_advanced_settings_put_and_persist(test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store):
    app = FastAPI()
    app.include_router(create_admin_router(
        test_settings, project_registry, advanced_settings_store, log_buffer, conversation_store
    ))
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
    assert "서버 로그" in response.text
    assert 'id="console"' in response.text


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
    assert "데이터 조회" in response.text
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
