#!/bin/bash
set -e

echo "🚀 Remote AI Coder 실행을 준비합니다..."

# 1. Conda 환경 활성화
# bash 스크립트 내에서 conda activate를 사용하기 위한 초기화
eval "$(conda shell.bash hook 2> /dev/null || echo '')"
conda activate remote-coder || { echo "❌ conda 환경 'remote-coder'를 찾을 수 없습니다."; exit 1; }
echo "✅ Conda 환경(remote-coder) 활성화 완료"

# 2. 기존 ngrok 종료 (충돌 방지)
pkill ngrok || true

# 3. ngrok 백그라운드 실행 (포트 8000)
echo "🌐 ngrok 터널을 시작합니다..."
ngrok http 8000 > /dev/null 2>&1 &
NGROK_PID=$!

# 터널이 완전히 열릴 때까지 잠시 대기
sleep 2

# 4. ngrok URL 추출 (파이썬 사용 - jq 없이 동작)
PUBLIC_URL=$(python -c "
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
except Exception as e:
    sys.exit(1)
")

if [ -z "$PUBLIC_URL" ]; then
    echo "❌ ngrok URL을 가져오지 못했습니다. ngrok이 제대로 실행되었는지 확인해주세요."
    kill $NGROK_PID
    exit 1
fi

echo "🔗 발급된 ngrok HTTPS 주소: $PUBLIC_URL"

# 5. 웹훅 등록 스크립트 실행
if ! python scripts/set_webhook.py "$PUBLIC_URL"; then
    echo "⚠️ 웹훅 등록에 실패했습니다. 기존 웹훅이 살아있다면 동작할 수 있으니 서버를 계속 시작합니다."
fi

# 6. 서버 종료 시 ngrok도 함께 종료되도록 트랩 설정
trap "echo -e '\n🛑 서버와 터널을 종료합니다...'; kill $NGROK_PID; exit 0" SIGINT SIGTERM

# 7. FastAPI 서버 실행
echo "🚀 FastAPI 서버를 시작합니다..."
uvicorn app.main:app --reload
