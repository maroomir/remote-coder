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
- `TELEGRAM_ALLOWED_USER_IDS` (선택)
- `PROJECT_ROOT`
- `WORKTREE_BASE_DIR`
- 필요 시 `TELEGRAM_WEBHOOK_SECRET`

## 3) 한 번에 실행하기 (권장)

미리 작성된 `run.sh` 스크립트를 사용하면 Conda 환경 활성화, ngrok 실행, Webhook 등록, 서버 실행을 모두 한 번에 처리합니다.

```bash
./run.sh
```

- 스크립트 실행 후 텔레그램에서 바로 봇에게 말을 걸면 동작합니다.
- 서버를 종료하려면 `Ctrl+C`를 누르면 ngrok도 함께 종료됩니다.

## 4) 지원 명령어 (MVP)

- `/start` : 봇 사용 안내
- `/help` : 명령어 도움말
- `/model` : 기본 모델 확인
- `/model claude` : 현재 chat의 기본 모델을 claude로 변경
- `/model codex` : 현재 chat의 기본 모델을 codex로 변경
- `/status <job_id>` : 작업 상태 조회
- `/projects` : 등록 프로젝트 목록
- 자연어 메시지: AI 작업 요청 생성

참고:

- `/model`로 변경한 기본 모델은 MVP에서는 인메모리 저장입니다. 서버 재시작 시 초기화됩니다.
- 자연어 메시지에서 `model: codex`, `branch: my-branch`, `no commit` 토큰을 함께 사용할 수 있습니다.

## 6) 테스트

```bash
conda activate remote-coder
pytest -q
```
