import asyncio
import threading

import pytest

import app.main as main


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

    assert started.wait(timeout=1)
    release.set()
    await context.__aexit__(None, None, None)
