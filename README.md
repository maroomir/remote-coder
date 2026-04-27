# Remote AI Coder

텔레그램 메시지를 통해 로컬 개발 머신에서 AI 코딩 작업을 실행하고 Git 브랜치/커밋 결과를 알림으로 받는 MVP 프로젝트입니다.

## 1) 환경 준비 (Conda)

```bash
conda env create -f environment.yml
conda activate remote-coder
```

## 2) 설정

```bash
cp .env.example .env
```

`.env`에 다음 값을 채웁니다.

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_ALLOWED_CHAT_IDS`
- `PROJECT_ROOT`
- `WORKTREE_BASE_DIR`
- 필요 시 `TELEGRAM_WEBHOOK_SECRET`

## 3) 서버 실행

```bash
uvicorn app.main:app --reload
```

헬스체크:

```bash
curl http://127.0.0.1:8000/health
```

## 4) Telegram Webhook 등록 예시

```bash
curl -X POST "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook" \
  -d "url=<PUBLIC_HTTPS_URL>/telegram/webhook" \
  -d "secret_token=<TELEGRAM_WEBHOOK_SECRET>"
```

`<PUBLIC_HTTPS_URL>`는 ngrok 등 HTTPS 터널 주소를 사용합니다.

## 5) 지원 명령어 (MVP)

- `/start` : 봇 사용 안내
- `/help` : 명령어 도움말
- `/model` : 기본 모델 확인
- `/model claude` : Claude 관련 안내
- `/model codex` : Codex 관련 안내
- `/status <job_id>` : 작업 상태 조회
- `/projects` : 등록 프로젝트 목록
- 자연어 메시지: AI 작업 요청 생성

## 6) 테스트

```bash
pytest -q
```
