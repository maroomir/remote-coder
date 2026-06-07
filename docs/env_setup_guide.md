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
- 본인이 원하는 충분히 긴 임의 문자열을 사용하세요. 예시는 문서용이며 실제 값으로 쓰지 마세요.

> [!WARNING]
> `.env`의 Bot Token, Chat/User ID, webhook secret, 개인 경로는 공개 저장소에 커밋하지 마세요. 기존 private 저장소를 public으로 전환하기 전에는 Git 히스토리 secret scan과 토큰 재발급을 권장합니다.

### 경로 및 기타 설정들
현재 환경을 기준으로 다음과 같이 설정하시면 됩니다.
- `PROJECT_ROOT`: 대상 프로젝트 최상위 폴더의 절대 경로 (예: `/Users/yourname/Git/remote-coder` 또는 `/home/yourname/Git/remote-coder`)
- `WORKTREE_BASE_DIR`: AI가 임시로 작업할 공간의 절대 경로 (예: `/Users/yourname/Git/remote-coder-worktrees` 또는 `/home/yourname/Git/remote-coder-worktrees`) 폴더는 작업 시 자동으로 생성됩니다.

나머지 기본 설정값:
- `DEFAULT_MODEL=claude` (사용할 AI 모델)
- `DEFAULT_PROJECT=remote-coder` (프로젝트 이름)
- `JOB_TIMEOUT_SECONDS=1800` (작업 최대 허용 시간 - 30분)
- `KEEP_WORKTREE_ON_SUCCESS=true` (작업 성공 후 임시 폴더 유지 여부)
- `GIT_REMOTE_NAME=origin` (선택, 기본 `origin`) — Job 커밋 후 push, `/rebase`, `/clear` 시 사용하는 Git 원격 이름입니다.

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
PROJECT_ROOT=/Users/yourname/Git/remote-coder
WORKTREE_BASE_DIR=/Users/yourname/Git/remote-coder-worktrees
JOB_TIMEOUT_SECONDS=1800
KEEP_WORKTREE_ON_SUCCESS=true
```

추가 사용 팁:

- `/model claude`, `/model codex`는 현재 chat의 기본 모델을 바꿉니다. (서버 재시작 전까지 유지)
- 자연어 요청에 `model: codex`, `branch: remote/test`, `no commit` 토큰을 함께 쓰면 요청별 옵션을 지정할 수 있습니다.
- AI Job은 변경이 없으면 브랜치를 만들지 않습니다. 변경이 있으면 브랜치·커밋 후 `GIT_REMOTE_NAME`으로 push합니다.
- `/monitor branch`로 브랜치 목록·요약을, `/branch`로 현재 브랜치를, `/branch <이름>`으로 로컬 브랜치가 있을 때만 `git switch` 할 수 있습니다(대상은 이 채팅의 적용 프로젝트).
- `/rebase`는 이 채팅 적용 프로젝트 저장소에서 동작합니다. 인자 없으면 로컬과 원격에 모두 있는 브랜치를 인라인 버튼으로 선택합니다.
- `/clear`는 등록된 enabled 프로젝트마다 `remote-*` 이름의 로컬·원격 브랜치를 삭제합니다. 실행 전 의도를 다시 확인하세요.
- 관리 UI(`/`, `/projects`, `/advanced`, `/logs`, `/database`)는 localhost 전용으로 사용하세요. ngrok이나 reverse proxy로 외부에 공개하면 로그와 SQLite 대화 기억이 노출될 수 있습니다.

이렇게 `.env` 파일을 저장해두면, 앱이 실행될 때 설정 파일이 이 값들을 읽어와서 시스템이 봇을 조종하고 안전하게 인증을 처리할 수 있게 됩니다. 

*(주의: `.env` 파일은 보안상 매우 중요하므로 깃허브 등의 공개된 저장소에 절대 올라가면 안 됩니다. 이 프로젝트의 `.gitignore`에는 이미 `.env`가 제외되도록 설정되어 있습니다.)*

---

## 3. 서버 실행 및 웹훅 등록 방법 (초간단 방식)

`remote-coder up` 한 줄이 ngrok 실행, Webhook 등록, 서버 실행을 모두 처리합니다.

### 터미널에서 다음 명령어를 실행하세요:
```bash
remote-coder up
```

다음 작업들을 자동으로 수행합니다:
1. `ngrok` 터널 생성 및 공개 HTTPS 주소 가져오기
2. 발급된 ngrok 주소로 활성 프로젝트의 Telegram webhook 등록 (`setWebhook`)
3. FastAPI 봇 서버 실행

서버를 끄고 싶을 때는 터미널에서 `Ctrl+C`를 누르면 `ngrok`과 서버가 함께 안전하게 종료됩니다.

---

### (참고) 수동으로 설정해야 하는 분들을 위한 기존 가이드

아래는 스크립트를 사용하지 않고 단계별로 진행하고자 하는 경우를 위한 가이드입니다.

### 3.1 수동 서버 실행

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

> [!CAUTION]
> ngrok 등으로 외부에 노출해야 하는 경로는 Telegram webhook(`/telegram/webhook`)입니다. 관리 UI 경로를 외부 사용자가 접근할 수 있게 라우팅하지 마세요.

```bash
ngrok http 8000
```

실행 후 `https://xxxx-xx-xx-xx-xx.ngrok-free.app` 같은 주소가 보입니다.  
이 주소를 아래에서 `<PUBLIC_HTTPS_URL>`로 사용합니다.

예시:

- `<PUBLIC_HTTPS_URL>` = `https://abcd-1234.ngrok-free.app`
- 실제 webhook URL = `https://abcd-1234.ngrok-free.app/telegram/webhook`

### 3.3 setWebhook 자동 등록 스크립트 실행

복잡한 `curl` 명령어 대신, 제공되는 파이썬 스크립트를 사용해 쉽게 웹훅을 등록할 수 있습니다.
터미널에 `conda activate remote-coder`가 활성화된 상태에서, 위에서 얻은 ngrok 주소를 인자로 넘겨 스크립트를 실행합니다.

```bash
python scripts/set_webhook.py <PUBLIC_HTTPS_URL>
# 예시: python scripts/set_webhook.py https://abcd-1234.ngrok-free.app
```

스크립트가 `.env` 파일의 봇 토큰과 시크릿 키를 자동으로 읽어서 텔레그램에 안전하게 등록해줍니다.
성공 시 `✅ 웹훅 등록 성공!` 메시지가 출력됩니다.

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

### 3.7 ngrok 주소가 바뀌었을 때 (재등록 방법)

무료 ngrok을 사용하면 ngrok을 껐다 켤 때마다 주소가 바뀝니다.
주소가 바뀌었을 때는 **바뀐 주소로 다시 스크립트만 실행**해주면 됩니다. (기존 웹훅을 덮어씁니다)

```bash
python scripts/set_webhook.py https://새로-발급된-주소.ngrok-free.app
```

만약 웹훅 자체를 완전히 삭제하고 싶다면 아래 명령어를 사용하세요:
```bash
curl -X POST "https://api.telegram.org/bot<내_봇_토큰>/deleteWebhook"
```
