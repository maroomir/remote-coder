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
TELEGRAM_WEBHOOK_SECRET=내가_정한_비밀번호
DEFAULT_MODEL=claude
DEFAULT_PROJECT=remote-coder
PROJECT_ROOT=/Users/maroomir/Git/maroomir/remote-coder
WORKTREE_BASE_DIR=/Users/maroomir/Git/maroomir/remote-coder-worktrees
JOB_TIMEOUT_SECONDS=1800
KEEP_WORKTREE_ON_SUCCESS=true
```

이렇게 `.env` 파일을 저장해두면, 앱이 실행될 때 설정 파일이 이 값들을 읽어와서 시스템이 봇을 조종하고 안전하게 인증을 처리할 수 있게 됩니다. 

*(주의: `.env` 파일은 보안상 매우 중요하므로 깃허브 등의 공개된 저장소에 절대 올라가면 안 됩니다. 이 프로젝트의 `.gitignore`에는 이미 `.env`가 제외되도록 설정되어 있습니다.)*
