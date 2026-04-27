# 환경 변수 및 텔레그램 봇 설정 가이드

이 문서에서는 `.env.example` 파일을 바탕으로 실제 `.env` 파일을 생성하고, 필요한 텔레그램 환경 변수 값들을 얻는 방법을 처음 접하는 분들의 눈높이에 맞춰 설명합니다.

## 1. 환경 변수 값 얻는 방법

### `TELEGRAM_BOT_TOKEN` (텔레그램 봇 토큰)
이 시스템을 대신해 메시지를 주고받을 "봇(Bot)"을 만들어야 합니다.
1. 스마트폰이나 PC의 텔레그램 앱을 엽니다.
2. 검색창에 **BotFather** 라고 검색하고 공식 계정(파란색 체크 표시가 있음)과 대화를 시작합니다.
3. 채팅창에 `/newbot` 이라고 입력합니다.
4. 봇의 이름(예: My Remote Coder)을 입력하라고 하면 원하는 이름을 입력합니다.
5. 봇의 사용자명(Username)을 입력하라고 하면, 반드시 끝이 `bot`으로 끝나는 영어 이름(예: `maroomir_coder_bot`)을 입력합니다.
6. 생성이 완료되면 `1234567890:ABCDefghIJKLmnopQRSTuvwxyz...` 와 같은 긴 형태의 **HTTP API Token**을 발급해 줍니다. 이 값이 토큰입니다.

### `TELEGRAM_ALLOWED_CHAT_IDS` (내 텔레그램 계정 ID)
아무나 내 봇에게 명령을 내리면 안 되므로, 내 계정(또는 내가 속한 채팅방)의 고유 ID만 허용해야 합니다.
1. 텔레그램 검색창에 **userinfobot** 또는 **GetIDs Bot** 등을 검색해서 봇과 대화를 시작합니다.
2. `/start` 를 누르면 내 계정의 ID 정보(보통 숫자 형태, 예: `123456789`)를 알려줍니다. 이 숫자가 내 ID입니다.
3. 여러 명을 허용하려면 쉼표(,)로 구분하여 입력할 수 있습니다. (예: `123456789,987654321`)

### `TELEGRAM_ALLOWED_USER_IDS` (선택: 허용할 유저 ID)
chat id allowlist 외에 user id 기준으로도 인증하고 싶다면 추가합니다.
- 비워두면 chat id allowlist만 사용합니다.
- 여러 명을 허용하려면 쉼표(,)로 구분합니다. (예: `123456789,987654321`)

### `TELEGRAM_WEBHOOK_SECRET` (웹훅 비밀키)
외부에서 내 서버로 텔레그램을 가장한 해킹/위조 요청이 들어오는 것을 막기 위한 비밀번호입니다.
- 본인이 원하는 임의의 영어/숫자 조합(예: `my-super-secret-key-2024`)을 마음대로 정하시면 됩니다. 

### 경로 및 기타 설정들
현재 환경을 기준으로 다음과 같이 설정하시면 됩니다.
- `PROJECT_ROOT`: 대상 프로젝트 최상위 폴더의 절대 경로 (예: `/Users/maroomir/Git/maroomir/remote-coder`)
- `WORKTREE_BASE_DIR`: AI가 임시로 작업할 공간의 절대 경로 (예: `/Users/maroomir/Git/maroomir/remote-coder-worktrees`) 폴더는 작업 시 자동으로 생성됩니다.

나머지 기본 설정값:
- `DEFAULT_MODEL=claude` (사용할 AI 모델)
- `DEFAULT_PROJECT=remote-coder` (프로젝트 이름)
- `JOB_TIMEOUT_SECONDS=1800` (작업 최대 허용 시간 - 30분)
- `KEEP_WORKTREE_ON_SUCCESS=true` (작업 성공 후 임시 폴더 유지 여부)

---

## 2. 환경 변수 등록(저장)하는 방법

터미널이나 VS Code 등에서 `.env.example` 파일을 복사하여 숨김 파일인 `.env` 파일을 생성하고 거기에 위에서 얻은 값들을 입력해야 합니다.

1. 프로젝트 최상위 폴더에 있는 `.env.example` 파일을 복사하여 `.env` 라는 이름의 새 파일을 생성합니다. (터미널에서는 `cp .env.example .env` 명령어를 사용할 수 있습니다.)
2. 방금 생성된 `.env` 파일을 열어 아래 예시와 같이 실제 값들로 수정해줍니다.

**`.env` 파일 작성 예시:**
```env
TELEGRAM_BOT_TOKEN=봇파더가_알려준_토큰값_그대로_붙여넣기
TELEGRAM_ALLOWED_CHAT_IDS=내_텔레그램_숫자_ID
TELEGRAM_ALLOWED_USER_IDS=
TELEGRAM_WEBHOOK_SECRET=내가_정한_비밀번호
DEFAULT_MODEL=claude
DEFAULT_PROJECT=remote-coder
PROJECT_ROOT=/Users/maroomir/Git/maroomir/remote-coder
WORKTREE_BASE_DIR=/Users/maroomir/Git/maroomir/remote-coder-worktrees
JOB_TIMEOUT_SECONDS=1800
KEEP_WORKTREE_ON_SUCCESS=true
```

추가 사용 팁:

- `/model claude`, `/model codex`는 현재 chat의 기본 모델을 바꿉니다. (서버 재시작 전까지 유지)
- 자연어 요청에 `model: codex`, `branch: remote/test`, `no commit` 토큰을 함께 쓰면 요청별 옵션을 지정할 수 있습니다.

이렇게 `.env` 파일을 저장해두면, 앱이 실행될 때 설정 파일이 이 값들을 읽어와서 시스템이 봇을 조종하고 안전하게 인증을 처리할 수 있게 됩니다. 

*(주의: `.env` 파일은 보안상 매우 중요하므로 깃허브 등의 공개된 저장소에 절대 올라가면 안 됩니다. 이 프로젝트의 `.gitignore`에는 이미 `.env`가 제외되도록 설정되어 있습니다.)*

---

## 3. Telegram Webhook 등록 방법 (처음 하는 분용)

이 프로젝트는 Telegram의 **Webhook 방식**으로 동작합니다.  
즉, 내가 `/start`를 보냈을 때 Telegram이 우리 서버의 `/telegram/webhook`으로 이벤트를 전달해야 합니다.

핵심은 아래 3가지입니다.

1. FastAPI 서버가 실행 중이어야 함
2. Telegram이 접근 가능한 HTTPS 주소가 있어야 함 (ngrok 등)
3. `setWebhook`에 등록한 `secret_token`이 `.env`의 `TELEGRAM_WEBHOOK_SECRET`와 같아야 함

### 3.1 서버 먼저 실행

프로젝트 루트에서:

```bash
conda activate remote-coder
uvicorn app.main:app --reload
```

별도 터미널에서 헬스체크:

```bash
curl http://127.0.0.1:8000/health
```

`{"status":"ok"}`가 나오면 정상입니다.

### 3.2 ngrok으로 HTTPS 공개 주소 만들기

Telegram은 로컬 `127.0.0.1`로 직접 보내지 못하므로 HTTPS 터널이 필요합니다.

```bash
ngrok http 8000
```

실행 후 `https://xxxx-xx-xx-xx-xx.ngrok-free.app` 같은 주소가 보입니다.  
이 주소를 아래에서 `<PUBLIC_HTTPS_URL>`로 사용합니다.

예시:

- `<PUBLIC_HTTPS_URL>` = `https://abcd-1234.ngrok-free.app`
- 실제 webhook URL = `https://abcd-1234.ngrok-free.app/telegram/webhook`

### 3.3 setWebhook 등록

아래 명령의 `<TELEGRAM_BOT_TOKEN>`, `<PUBLIC_HTTPS_URL>`, `<TELEGRAM_WEBHOOK_SECRET>`를 실제 값으로 바꿔서 실행합니다.

```bash
curl -X POST "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook" \
  -d "url=<PUBLIC_HTTPS_URL>/telegram/webhook" \
  -d "secret_token=<TELEGRAM_WEBHOOK_SECRET>"
```

성공하면 보통 `{"ok":true,"result":true,...}`가 반환됩니다.

### 3.4 등록 상태 확인 (매우 중요)

```bash
curl "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/getWebhookInfo"
```

확인 포인트:

- `url`이 비어 있지 않아야 함
- `url`이 `<PUBLIC_HTTPS_URL>/telegram/webhook`와 일치해야 함
- `last_error_message`가 없어야 함

### 3.5 실제 동작 확인

1. Telegram 앱에서 내 봇에 `/start` 전송
2. 서버 터미널(`uvicorn`)에 `/telegram/webhook` 요청 로그가 찍히는지 확인
3. 봇이 안내 메시지로 응답하면 완료

### 3.6 자주 막히는 원인 체크리스트

- ngrok URL이 바뀌었는데 `setWebhook`를 다시 안 함
- `secret_token`과 `.env`의 `TELEGRAM_WEBHOOK_SECRET` 값이 다름
- `TELEGRAM_ALLOWED_CHAT_IDS` 또는 `TELEGRAM_ALLOWED_USER_IDS` 값이 실제 계정/채팅 ID와 다름
- 서버가 꺼져 있거나 다른 포트에서 실행 중
- 봇 토큰 오타

### 3.7 webhook 초기화/재등록 방법

등록이 꼬였을 때는 먼저 삭제 후 다시 등록하면 깔끔합니다.

삭제:

```bash
curl -X POST "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/deleteWebhook"
```

그 다음 `3.3 setWebhook 등록`을 다시 실행하세요.
