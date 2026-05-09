#!/bin/bash
set -e

NGROK_PID=""
PUBLIC_URL=""

activate_conda_env() {
    # bash 스크립트 내에서 conda activate를 사용하기 위한 초기화
    eval "$(conda shell.bash hook 2> /dev/null || echo '')"
    conda activate remote-coder || {
        echo "❌ conda 환경 'remote-coder'를 찾을 수 없습니다."
        exit 1
    }
    echo "✅ Conda 환경(remote-coder) 활성화 완료"
}

ensure_ngrok_configured() {
    if ngrok config check 2>&1 | grep -q "Valid configuration"; then
        return
    fi

    echo "❌ ngrok 설정이 유효하지 않거나 AuthToken이 없습니다."
    echo "💡 https://dashboard.ngrok.com 에서 회원가입 후 AuthToken을 발급받으세요."
    echo "💡 실행 명령어: ngrok config add-authtoken <your-token>"
    exit 1
}

stop_existing_ngrok() {
    # 기존 ngrok 종료 (충돌 방지)
    pkill ngrok || true
}

start_ngrok() {
    echo "🌐 ngrok 터널을 시작합니다..."
    ngrok http 8000 > /dev/null 2>&1 &
    NGROK_PID=$!

    # 터널이 완전히 열릴 때까지 잠시 대기
    sleep 2
}

fetch_public_url() {
    # ngrok URL 추출 (파이썬 사용 - jq 없이 동작)
    python -c "
import urllib.request
import json
import sys
try:
    req = urllib.request.urlopen('http://127.0.0.1:4040/api/tunnels')
    data = json.loads(req.read().decode('utf-8'))
    tunnels = data.get('tunnels', [])
    for t in tunnels:
        if t.get('public_url', '').startswith('https'):
            print(t['public_url'])
            sys.exit(0)
    sys.exit(1)
except Exception:
    sys.exit(1)
"
}

stop_ngrok_process() {
    if [ -n "$NGROK_PID" ]; then
        kill "$NGROK_PID" 2> /dev/null || true
    fi
}

ensure_public_url() {
    if [ -n "$PUBLIC_URL" ]; then
        echo "🔗 발급된 ngrok HTTPS 주소: $PUBLIC_URL"
        return
    fi

    echo "❌ ngrok URL을 가져오지 못했습니다. ngrok이 제대로 실행되었는지 확인해주세요."
    stop_ngrok_process
    exit 1
}

register_webhook() {
    if ! python scripts/set_webhook.py "$PUBLIC_URL"; then
        echo "⚠️ 웹훅 등록에 실패했습니다. 기존 웹훅이 살아있다면 동작할 수 있으니 서버를 계속 시작합니다."
    fi
}

cleanup() {
    echo -e "\n🛑 서버와 터널을 종료합니다..."
    stop_ngrok_process
    exit 0
}

start_server() {
    echo "🚀 FastAPI 서버를 시작합니다..."
    export TELEGRAM_WEBHOOK_PUBLIC_BASE_URL="$PUBLIC_URL"
    uvicorn app.main:app --reload
}

main() {
    echo "🚀 Remote AI Coder 실행을 준비합니다..."
    activate_conda_env
    ensure_ngrok_configured
    stop_existing_ngrok
    start_ngrok
    PUBLIC_URL="$(fetch_public_url || true)"
    ensure_public_url
    register_webhook
    trap cleanup SIGINT SIGTERM
    start_server
}

main "$@"
