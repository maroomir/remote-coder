from __future__ import annotations

"""등록된 활성 프로젝트마다 Telegram setWebhook 과 setMyCommands 를 호출합니다.

공개 HTTPS Base URL 하나를 넘기면 `build_public_webhook_url(base, bot_token)` 규칙으로
프로젝트별 전체 webhook URL을 만들고, 비활성·삭제된 프로젝트는 스크립트 대상에서 빠집니다.
Telegram에 예전 URL이 남은 봇은 Bot API deleteWebhook 또는 이 스크립트 재실행으로 정리합니다.
"""

import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def register_webhook(
    api_url: str,
    webhook_url: str,
    webhook_secret: str | None,
) -> bool:
    max_attempts = 3
    connect_timeout = 10.0
    request_timeout = 30.0

    payload: dict[str, object] = {
        "url": webhook_url,
        "drop_pending_updates": True,
    }
    if webhook_secret:
        payload["secret_token"] = webhook_secret

    for attempt in range(1, max_attempts + 1):
        print(f"  텔레그램 서버에 요청 중... ({attempt}/{max_attempts})")
        try:
            response = httpx.post(
                api_url,
                json=payload,
                timeout=httpx.Timeout(request_timeout, connect=connect_timeout),
            )
            response.raise_for_status()
            result = response.json()

            if result.get("ok"):
                print("  ✅ 웹훅 등록 성공!")
                desc = result.get("description")
                if desc:
                    print(f"  응답: {desc}")
                return True

            print("  ❌ 웹훅 등록 실패!")
            print(f"  에러: {result}")
            return False
        except httpx.HTTPError as e:
            print(f"  ❌ HTTP 요청 실패: {e}")
            if attempt < max_attempts:
                wait_seconds = attempt * 2
                print(f"  ⏳ {wait_seconds}초 후 재시도합니다...")
                time.sleep(wait_seconds)

    return False


def register_bot_commands(api_url: str, commands: list[dict[str, str]]) -> bool:
    max_attempts = 3
    connect_timeout = 10.0
    request_timeout = 30.0

    for attempt in range(1, max_attempts + 1):
        print(f"  텔레그램 명령어 메뉴 등록 중... ({attempt}/{max_attempts})")
        try:
            response = httpx.post(
                api_url,
                json={"commands": commands},
                timeout=httpx.Timeout(request_timeout, connect=connect_timeout),
            )
            response.raise_for_status()
            result = response.json()

            if result.get("ok"):
                print("  ✅ 명령어 메뉴 등록 성공!")
                return True

            print("  ❌ 명령어 메뉴 등록 실패!")
            print(f"  에러: {result}")
            return False
        except httpx.HTTPError as e:
            print(f"  ❌ HTTP 요청 실패: {e}")
            if attempt < max_attempts:
                wait_seconds = attempt * 2
                print(f"  ⏳ {wait_seconds}초 후 재시도합니다...")
                time.sleep(wait_seconds)

    return False


def main() -> None:
    if len(sys.argv) < 2:
        print("사용법: python scripts/set_webhook.py <PUBLIC_HTTPS_URL>")
        print("예시: python scripts/set_webhook.py https://abcd-1234.ngrok-free.app")
        print("")
        print("프로젝트 레지스트리(.remote-coder/projects.json 등)에 등록된")
        print("활성화(enabled) 프로젝트마다 봇 토큰으로 setWebhook/setMyCommands 를 호출합니다.")
        sys.exit(1)

    public_url = sys.argv[1].rstrip("/")
    if not public_url.startswith("https://"):
        print("에러: URL은 반드시 https:// 로 시작해야 합니다.")
        sys.exit(1)

    load_dotenv()

    from app.config import get_settings
    from app.projects.registry import (
        ProjectRegistry,
        build_public_webhook_url,
        projects_config_path_for_settings,
    )
    from app.telegram.commands import default_telegram_bot_commands

    settings = get_settings()
    config_path = projects_config_path_for_settings(
        settings.project_root,
        settings.projects_config_path,
    )
    registry = ProjectRegistry(config_path)
    registry.load()

    enabled = [p for p in registry.list_projects() if p.enabled]
    if not enabled:
        print(
            f"에러: 활성화된 프로젝트가 없습니다. ({config_path})",
        )
        sys.exit(1)

    print(f"설정 파일: {config_path}")
    print(f"대상: 활성화 프로젝트 {len(enabled)}개")
    print("")
    bot_commands = default_telegram_bot_commands()

    any_failed = False
    for record in enabled:
        token = record.bot_token.get_secret_value().strip()
        if not token:
            print(f"[{record.name}] ❌ bot_token 이 비어 있습니다.")
            any_failed = True
            continue

        webhook_url = build_public_webhook_url(public_url, token)
        webhook_api_url = f"https://api.telegram.org/bot{token}/setWebhook"
        commands_api_url = f"https://api.telegram.org/bot{token}/setMyCommands"
        secret = (
            record.webhook_secret.get_secret_value().strip()
            if record.webhook_secret
            else ""
        ) or None

        print(f"[{record.name}] 웹훅 URL: {webhook_url}")
        if secret:
            print(f"[{record.name}] secret_token: 등록함")
        else:
            print(f"[{record.name}] secret_token: 없음 (선택 사항)")

        try:
            if not register_webhook(
                api_url=webhook_api_url,
                webhook_url=webhook_url,
                webhook_secret=secret,
            ):
                any_failed = True
            if not register_bot_commands(commands_api_url, bot_commands):
                any_failed = True
        except Exception as e:
            print(f"[{record.name}] ❌ 알 수 없는 에러: {e}")
            any_failed = True
        print("")

    if any_failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
