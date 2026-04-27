import sys
import os
import httpx
from dotenv import load_dotenv

def main():
    if len(sys.argv) < 2:
        print("사용법: python scripts/set_webhook.py <PUBLIC_HTTPS_URL>")
        print("예시: python scripts/set_webhook.py https://abcd-1234.ngrok-free.app")
        sys.exit(1)

    public_url = sys.argv[1].rstrip("/")
    if not public_url.startswith("https://"):
        print("에러: URL은 반드시 https:// 로 시작해야 합니다.")
        sys.exit(1)

    # .env 파일 로드
    load_dotenv()

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    webhook_secret = os.getenv("TELEGRAM_WEBHOOK_SECRET")

    if not bot_token:
        print("에러: .env 파일에 TELEGRAM_BOT_TOKEN이 설정되어 있지 않습니다.")
        sys.exit(1)
    if not webhook_secret:
        print("에러: .env 파일에 TELEGRAM_WEBHOOK_SECRET이 설정되어 있지 않습니다.")
        sys.exit(1)

    webhook_url = f"{public_url}/telegram/webhook"
    api_url = f"https://api.telegram.org/bot{bot_token}/setWebhook"

    print(f"웹훅 URL을 다음으로 설정합니다: {webhook_url}")
    print("텔레그램 서버에 요청 중...")

    try:
        response = httpx.post(
            api_url,
            json={
                "url": webhook_url,
                "secret_token": webhook_secret,
                "drop_pending_updates": True,
            },
            timeout=30.0
        )
        response.raise_for_status()
        result = response.json()
        
        if result.get("ok"):
            print("✅ 웹훅 등록 성공!")
            print(f"응답: {result.get('description')}")
        else:
            print("❌ 웹훅 등록 실패!")
            print(f"에러: {result}")
            sys.exit(1)
            
    except httpx.HTTPError as e:
        print(f"❌ HTTP 요청 실패: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ 알 수 없는 에러 발생: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
