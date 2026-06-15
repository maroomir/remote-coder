import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import app.main as main


def test_run_startup_side_effects_calls_pull_with_keyword_arguments(monkeypatch):
    pull = MagicMock()
    recover = MagicMock()
    monkeypatch.setattr(main, "run_startup_project_pulls", pull)
    monkeypatch.setattr(main, "recover_startup_jobs", recover)
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
    recover.assert_called_once_with(
        job_store=main.job_store,
        run_job=main.job_manager.recover,
        record_final_job_result=main._record_recovered_job_result,
        system_log=main._systemlog,
    )


@pytest.mark.asyncio
async def test_lifespan_does_not_wait_for_startup_side_effects(monkeypatch):
    started = asyncio.Event()
    release = asyncio.Event()

    async def block_startup_side_effects(_instances, _advanced_settings):
        started.set()
        await release.wait()

    monkeypatch.setattr(main.bot_instance_manager, "list_all", lambda: [])
    monkeypatch.setattr(
        main, "_run_startup_side_effects_in_background", block_startup_side_effects
    )

    context = main.lifespan(main.app)
    await asyncio.wait_for(context.__aenter__(), timeout=0.2)
    await asyncio.sleep(0)

    assert started.is_set()
    release.set()
    await context.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_lifespan_shutdown_survives_startup_side_effect_failure(monkeypatch):
    failed = asyncio.Event()

    def fail_startup_side_effects(_instances, _advanced_settings):
        failed.set()
        raise TypeError("startup failed")

    async def fake_to_thread(func, *args):
        return func(*args)

    monkeypatch.setattr(main.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(main, "_run_startup_side_effects", fail_startup_side_effects)

    await main._run_startup_side_effects_in_background([], SimpleNamespace())
    assert failed.is_set()
