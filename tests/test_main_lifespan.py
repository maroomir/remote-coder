import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import app.main as main


def test_run_startup_side_effects_calls_pull_with_keyword_arguments(monkeypatch):
    pull = MagicMock()
    monkeypatch.setattr(main, "run_startup_project_pulls", pull)
    monkeypatch.setattr(main.project_registry, "list_projects", lambda: [])

    main._run_startup_side_effects(
        [],
        SimpleNamespace(
            pull_projects_on_server_startup_enabled=True,
            git_remote_name="origin",
        ),
    )

    pull.assert_called_once_with(
        pull_projects_on_server_startup_enabled=True,
        project_registry=main.project_registry,
        git_service=main.git_service,
        remote="origin",
        system_log=main._systemlog,
    )


@pytest.mark.asyncio
async def test_lifespan_does_not_wait_for_startup_side_effects(monkeypatch):
    started = threading.Event()
    release = threading.Event()

    def block_startup_side_effects(_instances, _advanced_settings):
        started.set()
        release.wait(timeout=2)

    monkeypatch.setattr(main.bot_instance_manager, "list_all", lambda: [])
    monkeypatch.setattr(main, "_run_startup_side_effects", block_startup_side_effects)

    context = main.lifespan(main.app)
    await asyncio.wait_for(context.__aenter__(), timeout=0.2)

    assert await asyncio.to_thread(started.wait, 1)
    release.set()
    await context.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_lifespan_shutdown_survives_startup_side_effect_failure(monkeypatch):
    failed = threading.Event()

    def fail_startup_side_effects(_instances, _advanced_settings):
        failed.set()
        raise TypeError("startup failed")

    monkeypatch.setattr(main.bot_instance_manager, "list_all", lambda: [])
    monkeypatch.setattr(main, "_run_startup_side_effects", fail_startup_side_effects)

    context = main.lifespan(main.app)
    await context.__aenter__()
    assert await asyncio.to_thread(failed.wait, 1)
    await context.__aexit__(None, None, None)
