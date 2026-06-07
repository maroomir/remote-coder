from __future__ import annotations

import argparse
import os
import shutil
from collections.abc import Sequence
from pathlib import Path

import uvicorn

from app import __version__

_AI_CLI_TOOLS = ("claude", "codex", "gemini")
_VALID_MODELS = ("claude", "codex", "gemini")


def _add_server_args(subparser: argparse.ArgumentParser) -> None:
    subparser.add_argument("--host", default="127.0.0.1", help="Host interface to bind")
    subparser.add_argument("--port", default=8000, type=int, help="Port to bind")
    subparser.add_argument("--reload", action="store_true", help="Enable Uvicorn reload mode")
    subparser.add_argument("--log-level", default="info", help="Uvicorn log level")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="remote-coder")
    parser.add_argument("--version", action="version", version=f"remote-coder {__version__}")

    subparsers = parser.add_subparsers(dest="command")

    init = subparsers.add_parser("init", help="Interactive first-time setup (writes global config)")
    init.add_argument("--force", action="store_true", help="Overwrite existing config without asking")

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

    if args.command == "init":
        run_init(force=args.force)
    elif args.command == "doctor":
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
        print("⚠️ 일부 프로젝트 webhook 등록에 실패했습니다. 기존 등록이 유효하면 계속 동작할 수 있습니다.")

    try:
        _run_server(host=host, port=port, reload=reload, log_level=log_level)
    finally:
        ngrok.stop()
        print("🛑 ngrok 터널을 종료했습니다.")


def run_init(*, force: bool) -> None:
    from app.config import Settings, remote_coder_home
    from app.projects.registry import ProjectRegistry, projects_config_path_for_settings

    home = remote_coder_home()
    env_path = home / ".env"
    if env_path.exists() and not force:
        answer = input(f"이미 설정 파일이 있습니다 ({env_path}). 덮어쓸까요? [y/N]: ").strip().lower()
        if answer not in ("y", "yes"):
            print("설정을 취소했습니다.")
            return

    print("Remote AI Coder 설정을 시작합니다. (Ctrl+C로 취소)\n")

    project_root = _prompt_existing_dir("AI 작업 대상 Git 저장소 경로")
    worktree_dir = Path(
        _prompt("worktree 디렉터리", default=str(home / "worktrees"))
    ).expanduser()
    default_project = _prompt("프로젝트 이름", default=project_root.name)
    bot_token = _prompt_required("Telegram Bot Token (BotFather)")
    chat_ids = _prompt_chat_ids("허용할 Telegram Chat ID (쉼표로 구분)")
    model = _prompt_choice("기본 모델", _VALID_MODELS, default="claude")

    env_values = {
        "TELEGRAM_BOT_TOKEN": bot_token,
        "TELEGRAM_ALLOWED_CHAT_IDS": ",".join(str(cid) for cid in chat_ids),
        "DEFAULT_MODEL": model,
        "DEFAULT_PROJECT": default_project,
        "PROJECT_ROOT": str(project_root),
        "WORKTREE_BASE_DIR": str(worktree_dir),
    }
    _write_env_file(env_path, env_values)
    print(f"\n✅ 설정을 저장했습니다: {env_path}")

    settings = Settings(
        telegram_bot_token=bot_token,
        telegram_allowed_chat_ids=chat_ids,
        default_model=model,
        default_project=default_project,
        project_root=project_root,
        worktree_base_dir=worktree_dir,
        _env_file=None,
    )
    config_path = projects_config_path_for_settings(
        settings.project_root, settings.projects_config_path
    )
    registry = ProjectRegistry(config_path)
    registry.ensure_seeded_from_settings(settings)
    if registry.list_projects():
        print(f"✅ 프로젝트 레지스트리: {config_path}")
    else:
        print(f"ℹ️ 기존 프로젝트 레지스트리를 유지했습니다: {config_path}")

    print()
    run_doctor()
    print("\n다음 단계: `remote-coder up` 으로 서버를 실행하세요.")


def run_doctor() -> None:
    from app.tunnel import TunnelError, ensure_ngrok_available, ensure_ngrok_configured

    print("전제조건 점검:")
    try:
        ensure_ngrok_available()
        ensure_ngrok_configured()
        print("  ✅ ngrok: 설치 및 AuthToken 설정 완료")
    except TunnelError as exc:
        print(f"  ⚠️ ngrok: {exc}")

    available = [tool for tool in _AI_CLI_TOOLS if shutil.which(tool)]
    if available:
        print(f"  ✅ AI CLI: {', '.join(available)}")
    else:
        print(
            "  ⚠️ AI CLI(claude/codex/gemini)를 찾지 못했습니다. 최소 1개를 설치하세요. "
            "(예: npm install -g @anthropic-ai/claude-code)"
        )


def _prompt(label: str, *, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    if not value and default is not None:
        return default
    return value


def _prompt_required(label: str) -> str:
    while True:
        value = input(f"{label}: ").strip()
        if value:
            return value
        print("  값을 입력해주세요.")


def _prompt_existing_dir(label: str) -> Path:
    while True:
        raw = _prompt_required(label)
        path = Path(raw).expanduser().resolve()
        if path.is_dir():
            if not (path / ".git").exists():
                print(f"  ⚠️ {path} 는 Git 저장소가 아닌 것 같습니다. 계속 진행합니다.")
            return path
        print(f"  디렉터리를 찾을 수 없습니다: {path}")


def _prompt_chat_ids(label: str) -> list[int]:
    while True:
        raw = _prompt_required(label)
        try:
            return [int(item.strip()) for item in raw.split(",") if item.strip()]
        except ValueError:
            print("  숫자 Chat ID만 쉼표로 구분해 입력해주세요. (예: 123456789,987654321)")


def _prompt_choice(label: str, choices: Sequence[str], *, default: str) -> str:
    options = "/".join(choices)
    while True:
        value = _prompt(f"{label} ({options})", default=default).lower()
        if value in choices:
            return value
        print(f"  다음 중 하나를 입력해주세요: {options}")


def _write_env_file(env_path: Path, values: dict[str, str]) -> None:
    env_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{key}={value}" for key, value in values.items()]
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    # SECURITY: the global .env stores the plaintext bot token; restrict to the owner.
    os.chmod(env_path, 0o600)


if __name__ == "__main__":
    main()
