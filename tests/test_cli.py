from app import __version__
from app.cli import build_parser, main


def test_cli_version_matches_package() -> None:
    parser = build_parser()

    assert parser.prog == "remote-coder"
    assert __version__ == "0.3.0"


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
