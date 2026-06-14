import os

from app import __version__
from app.cli import build_parser, main


def test_cli_version_matches_package() -> None:
    parser = build_parser()

    assert parser.prog == "remote-coder"
    assert __version__ == "0.5.1"


def test_cli_exposes_all_subcommands() -> None:
    parser = build_parser()
    subactions = parser._subparsers._group_actions[0].choices

    assert set(subactions) == {"up", "doctor"}


def test_cli_up_no_tunnel_runs_server_only(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr("app.cli.uvicorn.run", lambda *a, **k: calls.append((a, k)))

    def fail_tunnel(*_a, **_k):  # pragma: no cover - must not be reached
        raise AssertionError("tunnel must not start with --no-tunnel")

    monkeypatch.setattr("app.tunnel.NgrokTunnel", fail_tunnel)

    main(["up", "--no-tunnel", "--port", "9100"])

    assert calls == [(("app.main:app",), {"host": "127.0.0.1", "port": 9100, "reload": False, "log_level": "info"})]


def test_cli_up_orchestrates_tunnel_register_and_serve(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_WEBHOOK_PUBLIC_BASE_URL", "")
    events = []

    class FakeTunnel:
        def __init__(self, port):
            events.append(("init", port))

        def start(self):
            events.append(("start",))
            return "https://abcd.ngrok-free.app"

        def stop(self):
            events.append(("stop",))

    monkeypatch.setattr("app.tunnel.NgrokTunnel", FakeTunnel)

    register_calls = []
    monkeypatch.setattr(
        "app.telegram.webhook_registration.register_all_enabled_projects",
        lambda url, settings: register_calls.append(url) or True,
    )

    class FakeGetSettings:
        def cache_clear(self):
            pass

        def __call__(self):
            return object()

    monkeypatch.setattr("app.config.get_settings", FakeGetSettings())

    run_calls = []
    monkeypatch.setattr("app.cli.uvicorn.run", lambda *a, **k: run_calls.append(k))

    main(["up", "--port", "8001"])

    assert ("init", 8001) in events
    assert events.index(("start",)) < events.index(("stop",))
    assert register_calls == ["https://abcd.ngrok-free.app"]
    assert os.environ["TELEGRAM_WEBHOOK_PUBLIC_BASE_URL"] == "https://abcd.ngrok-free.app"
    assert run_calls and run_calls[0]["port"] == 8001


def test_cli_doctor_reports_status(monkeypatch, capsys) -> None:
    monkeypatch.setattr("app.tunnel.ensure_ngrok_available", lambda: "/usr/bin/ngrok")
    monkeypatch.setattr("app.tunnel.ensure_ngrok_configured", lambda: None)
    monkeypatch.setattr(
        "shutil.which", lambda name: "/usr/bin/claude" if name == "claude" else None
    )

    main(["doctor"])

    out = capsys.readouterr().out
    assert "ngrok" in out
    assert "claude" in out
    assert "GitHub CLI" in out


def test_cli_up_no_tunnel_forwards_server_args(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr("app.cli.uvicorn.run", lambda *a, **k: calls.append((a, k)))

    main(["up", "--no-tunnel", "--host", "0.0.0.0", "--port", "9000", "--reload", "--log-level", "debug"])

    assert calls == [
        (
            ("app.main:app",),
            {"host": "0.0.0.0", "port": 9000, "reload": True, "log_level": "debug"},
        )
    ]


def test_cli_defaults_to_up(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_WEBHOOK_PUBLIC_BASE_URL", "")
    started = []

    class FakeTunnel:
        def __init__(self, port):
            pass

        def start(self):
            started.append(True)
            return "https://abcd.ngrok-free.app"

        def stop(self):
            pass

    monkeypatch.setattr("app.tunnel.NgrokTunnel", FakeTunnel)
    monkeypatch.setattr(
        "app.telegram.webhook_registration.register_all_enabled_projects",
        lambda url, settings: True,
    )

    class FakeGetSettings:
        def cache_clear(self):
            pass

        def __call__(self):
            return object()

    monkeypatch.setattr("app.config.get_settings", FakeGetSettings())

    run_calls = []
    monkeypatch.setattr("app.cli.uvicorn.run", lambda *a, **k: run_calls.append(k))

    main([])

    assert started == [True]
    assert run_calls and run_calls[0]["port"] == 8000
