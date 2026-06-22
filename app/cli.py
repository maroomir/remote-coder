from __future__ import annotations

import argparse
import os
from collections.abc import Sequence

import uvicorn

from app import __version__


def _add_server_args(subparser: argparse.ArgumentParser) -> None:
    subparser.add_argument("--host", default="127.0.0.1", help="Host interface to bind")
    subparser.add_argument("--port", default=8000, type=int, help="Port to bind")
    subparser.add_argument("--reload", action="store_true", help="Enable Uvicorn reload mode")
    subparser.add_argument("--log-level", default="info", help="Uvicorn log level")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="remote-coder")
    parser.add_argument("--version", action="version", version=f"remote-coder {__version__}")

    subparsers = parser.add_subparsers(dest="command")

    up = subparsers.add_parser(
        "up", help="Start ngrok tunnel, register Telegram webhooks, and run the server"
    )
    _add_server_args(up)
    up.add_argument(
        "--no-tunnel",
        action="store_true",
        help="Run the server only (skip ngrok and webhook registration)",
    )

    subparsers.add_parser("doctor", help="Check prerequisites (ngrok, AI CLIs, GitHub CLI)")
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        args = parser.parse_args(["up"])

    if args.command == "doctor":
        run_doctor()
    else:
        run_up(
            host=args.host,
            port=args.port,
            reload=args.reload,
            log_level=args.log_level,
            tunnel=not args.no_tunnel,
        )


def _run_server(*, host: str, port: int, reload: bool, log_level: str) -> None:
    print("🚀 Starting server... (press Ctrl+C to stop)")
    uvicorn.run("app.main:app", host=host, port=port, reload=reload, log_level=log_level)


def _prepare_secret_storage() -> None:
    """Enforce the secret-backend policy and migrate plaintext secrets once, before serving.

    Runs only when starting the server (`remote-coder up`), never on import, so tests that
    import ``app.main`` never touch the OS keyring or the user's real registry file.
    """
    from app.config import get_settings
    from app.projects.migration import mark_secret_backend, migrate_plaintext_to_keyring
    from app.projects.registry import projects_config_path
    from app.projects.secret_store import SECRET_BACKEND_KEYRING, build_secret_store

    config_path = projects_config_path(get_settings().projects_config_path)
    target = build_secret_store(config_path)  # raises (fail-closed) when no backend and no opt-in
    if target.backend_name == SECRET_BACKEND_KEYRING:
        migrate_plaintext_to_keyring(config_path, target)
        mark_secret_backend(config_path, SECRET_BACKEND_KEYRING)


def run_up(*, host: str, port: int, reload: bool, log_level: str, tunnel: bool = True) -> None:
    _prepare_secret_storage()

    if not tunnel:
        _run_server(host=host, port=port, reload=reload, log_level=log_level)
        return

    from app.config import get_settings
    from app.telegram.webhook_registration import register_all_enabled_projects
    from app.tunnel import NgrokTunnel, TunnelError

    ngrok = NgrokTunnel(port)
    try:
        print("🌐 Starting ngrok tunnel...")
        public_url = ngrok.start()
    except TunnelError as exc:
        print(f"❌ {exc}")
        raise SystemExit(1) from exc

    print(f"🔗 Public HTTPS URL: {public_url}")
    os.environ["TELEGRAM_WEBHOOK_PUBLIC_BASE_URL"] = public_url
    get_settings.cache_clear()
    settings = get_settings()

    print("📨 Registering Telegram webhooks and command menu...")
    if not register_all_enabled_projects(public_url, settings):
        if _has_enabled_projects(settings):
            print(
                "⚠️ Some project webhook registrations failed. "
                "If existing registrations are valid, the service may still work."
            )
        else:
            print(
                f"🛠️ No projects registered yet. Open http://127.0.0.1:{port}/ in a browser and "
                "register your first project (bot token, repository, allowed Chat IDs)."
            )

    try:
        _run_server(host=host, port=port, reload=reload, log_level=log_level)
    finally:
        ngrok.stop()
        print("🛑 ngrok tunnel stopped.")


def _has_enabled_projects(settings) -> bool:
    from app.projects.registry import ProjectRegistry, projects_config_path
    from app.projects.secret_store import secret_store_for_file

    config_path = projects_config_path(settings.projects_config_path)
    registry = ProjectRegistry(config_path, secret_store_for_file(config_path))
    registry.load()
    return any(project.enabled for project in registry.list_projects())


def run_doctor() -> None:
    from app.diagnostics import check_prerequisites

    report = check_prerequisites()
    print("Prerequisite checks:")
    if report.ngrok_ok:
        print("  ✅ ngrok: installed and AuthToken configured")
    else:
        print(f"  ⚠️ ngrok: {report.ngrok_detail}")

    installed = [cli.name for cli in report.ai_clis if cli.installed]
    if installed:
        print(f"  ✅ AI CLI: {', '.join(installed)}")
    else:
        print(
            "  ⚠️ AI CLI/provider (claude/codex/gemini/ollama) not found. Install at least one. "
            "(e.g. npm install -g @anthropic-ai/claude-code)"
        )
    if report.github_cli.installed:
        print("  ✅ GitHub CLI: gh")
    else:
        print("  ⚠️ GitHub CLI (gh) not found. Install it before using /pr.")


if __name__ == "__main__":
    main()
