import os

from app import __version__
from app.cli import build_parser, main


def test_cli_version_matches_package() -> None:
    parser = build_parser()

    assert parser.prog == "remote-coder"
    assert __version__ == "0.4.0"


def test_cli_exposes_all_subcommands() -> None:
    parser = build_parser()
    subactions = parser._subparsers._group_actions[0].choices

    assert set(subactions) == {"init", "up", "serve", "doctor"}


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
        "app.cli.shutil.which", lambda name: "/usr/bin/claude" if name == "claude" else None
    )

    main(["doctor"])

    out = capsys.readouterr().out
    assert "ngrok" in out
    assert "claude" in out


def test_cli_init_writes_config_and_registry(monkeypatch, tmp_path, capsys) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setenv("REMOTE_CODER_HOME", str(home))

    answers = iter(
        [
            str(repo),  # 대상 저장소 경로
            "",  # worktree (기본값)
            "",  # 프로젝트 이름 (기본값 = repo 이름)
            "123:abc-token",  # 봇 토큰
            "111,222",  # 허용 Chat ID
            "",  # 기본 모델 (기본값 claude)
        ]
    )
    monkeypatch.setattr("builtins.input", lambda *_a, **_k: next(answers))

    main(["init"])
    capsys.readouterr()

    env_path = home / ".env"
    assert env_path.exists()
    assert oct(env_path.stat().st_mode & 0o777) == oct(0o600)
    env_text = env_path.read_text(encoding="utf-8")
    assert "TELEGRAM_BOT_TOKEN=123:abc-token" in env_text
    assert f"PROJECT_ROOT={repo.resolve()}" in env_text
    assert "TELEGRAM_ALLOWED_CHAT_IDS=111,222" in env_text

    registry_path = repo / ".remote-coder" / "projects.json"
    assert registry_path.exists()


def test_cli_serve_runs_uvicorn(monkeypatch) -> None:
    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))

    monkeypatch.setattr("app.cli.uvicorn.run", fake_run)

    main(["serve", "--host", "0.0.0.0", "--port", "9000", "--reload", "--log-level", "debug"])

    assert calls == [
        (
            ("app.main:app",),
            {
                "host": "0.0.0.0",
                "port": 9000,
                "reload": True,
                "log_level": "debug",
            },
        )
    ]


def test_cli_defaults_to_serve(monkeypatch) -> None:
    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))

    monkeypatch.setattr("app.cli.uvicorn.run", fake_run)

    main([])

    assert calls == [
        (
            ("app.main:app",),
            {
                "host": "127.0.0.1",
                "port": 8000,
                "reload": False,
                "log_level": "info",
            },
        )
    ]
