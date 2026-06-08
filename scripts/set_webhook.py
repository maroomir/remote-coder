from __future__ import annotations

"""공개 HTTPS Base URL 하나로 활성 프로젝트마다 Telegram setWebhook/setMyCommands 를 호출합니다.

`remote-coder up` 과 동일한 등록 로직(`register_all_enabled_projects`)을 공유합니다. 비활성·삭제된
프로젝트는 대상에서 빠집니다. Telegram에 예전 URL이 남은 봇은 Bot API deleteWebhook 또는 이 스크립트
재실행으로 정리합니다.
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main() -> None:
    if len(sys.argv) < 2:
        print("사용법: python scripts/set_webhook.py <PUBLIC_HTTPS_URL>")
        print("예시: python scripts/set_webhook.py https://abcd-1234.ngrok-free.app")
        sys.exit(1)

    public_url = sys.argv[1].rstrip("/")
    if not public_url.startswith("https://"):
        print("에러: URL은 반드시 https:// 로 시작해야 합니다.")
        sys.exit(1)

    from app.config import get_settings
    from app.telegram.webhook_registration import register_all_enabled_projects

    settings = get_settings()
    print(f"공개 URL: {public_url}")
    print("활성 프로젝트의 Telegram webhook/명령어 메뉴를 등록합니다...")
    if not register_all_enabled_projects(public_url, settings):
        print("❌ 일부 프로젝트 등록에 실패했습니다. (자세한 내용은 서버 로그를 확인하세요)")
        sys.exit(1)
    print("✅ 등록 완료")


if __name__ == "__main__":
    main()
