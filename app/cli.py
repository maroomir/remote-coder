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

    subparsers.add_parser("doctor", help="Check prerequisites (ngrok, AI CLIs)")
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
    print("🚀 서버를 시작합니다... (종료: Ctrl+C)")
    uvicorn.run("app.main:app", host=host, port=port, reload=reload, log_level=log_level)


def run_up(*, host: str, port: int, reload: bool, log_level: str, tunnel: bool = True) -> None:
    if not tunnel:
        _run_server(host=host, port=port, reload=reload, log_level=log_level)
        return

    from app.config import get_settings
    from app.telegram.webhook_registration import register_all_enabled_projects
    from app.tunnel import NgrokTunnel, TunnelError

    ngrok = NgrokTunnel(port)
    try:
        print("🌐 ngrok 터널을 시작합니다...")
        public_url = ngrok.start()
    except TunnelError as exc:
        print(f"❌ {exc}")
        raise SystemExit(1) from exc

    print(f"🔗 공개 HTTPS 주소: {public_url}")
    os.environ["TELEGRAM_WEBHOOK_PUBLIC_BASE_URL"] = public_url
    get_settings.cache_clear()
    settings = get_settings()

    print("📨 Telegram webhook/명령어 메뉴를 등록합니다...")
    if not register_all_enabled_projects(public_url, settings):
        if _has_enabled_projects(settings):
            print("⚠️ 일부 프로젝트 webhook 등록에 실패했습니다. 기존 등록이 유효하면 계속 동작할 수 있습니다.")
        else:
            print(
                f"🛠️ 아직 등록된 프로젝트가 없습니다. 브라우저에서 http://127.0.0.1:{port}/ 를 열어 "
                "첫 프로젝트(봇 토큰·저장소·허용 Chat ID)를 등록하세요."
            )

    try:
        _run_server(host=host, port=port, reload=reload, log_level=log_level)
    finally:
        ngrok.stop()
        print("🛑 ngrok 터널을 종료했습니다.")


def _has_enabled_projects(settings) -> bool:
    from app.projects.registry import ProjectRegistry, projects_config_path_for_settings

    config_path = projects_config_path_for_settings(
        settings.project_root, settings.projects_config_path
    )
    registry = ProjectRegistry(config_path)
    registry.load()
    return any(project.enabled for project in registry.list_projects())


def run_doctor() -> None:
    from app.diagnostics import check_prerequisites

    report = check_prerequisites()
    print("전제조건 점검:")
    if report.ngrok_ok:
        print("  ✅ ngrok: 설치 및 AuthToken 설정 완료")
    else:
        print(f"  ⚠️ ngrok: {report.ngrok_detail}")

    installed = [cli.name for cli in report.ai_clis if cli.installed]
    if installed:
        print(f"  ✅ AI CLI: {', '.join(installed)}")
    else:
        print(
            "  ⚠️ AI CLI(claude/codex/gemini)를 찾지 못했습니다. 최소 1개를 설치하세요. "
            "(예: npm install -g @anthropic-ai/claude-code)"
        )


if __name__ == "__main__":
    main()
