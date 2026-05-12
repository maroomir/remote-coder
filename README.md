# Remote AI Coder

텔레그램 메시지를 통해 로컬 개발 머신에서 AI 코딩 작업을 실행하고 Git 브랜치/커밋 결과를 알림으로 받는 MVP 프로젝트입니다.

> [!WARNING]
> 이 프로젝트는 Telegram 메시지를 통해 로컬 머신의 AI CLI와 Git 작업을 실행합니다. 공개 인터넷에 서버나 관리 UI를 직접 노출하지 말고, 반드시 Telegram allowlist와(선택) webhook secret을 설정한 뒤 개인·신뢰 환경에서만 사용하세요.

## 멀티봇 모델 (요약)

- **등록 프로젝트마다 별도 Telegram 봇**을 둡니다. 채팅에서 대상 저장소를 바꾸는 `/project` 명령은 없습니다.
- Webhook 주소는 봇마다 다릅니다: `POST /telegram/webhook/{SHA256(봇토큰)의 16진 문자열 앞 16자리}` (토큰 자체는 URL에 넣지 않음).
- 봇 토큰·허용 Chat/User ID·(선택) webhook secret은 **프로젝트 레지스트리**(`projects.json` 등)에 저장됩니다. **토큰은 평문**이므로 파일 권한과 백업 정책을 엄격히 하세요.
- 상세 절차는 [`docs/multi-bot-setup.md`](docs/multi-bot-setup.md)를 참고하세요.
- 프로젝트를 **비활성화하거나 삭제**하면 서버는 해당 토큰 해시 prefix로 들어오는 업데이트를 더 이상 라우팅하지 않습니다. Telegram에 예전 URL이 남아 있어도 이 앱에서는 처리되지 않습니다. 봇 쪽 webhook을 비우거나 새 URL로 맞추려면 Bot API `deleteWebhook` 또는 [`scripts/set_webhook.py`](scripts/set_webhook.py)를 레지스트리에 맞게 다시 실행하세요.

## 공개/보안 안내

- `TELEGRAM_BOT_TOKEN`(시드용 선택), 레지스트리의 `bot_token`, Chat/User ID, webhook secret, AI API key, 개인 경로는 코드나 문서에 커밋하지 마세요.
- `.env`, `.remote-coder/`(특히 `projects.json`), worktree, 로그, SQLite 대화 기억 파일은 로컬 전용 데이터입니다. 이 저장소의 `.gitignore`는 기본적으로 이 파일들을 제외합니다.
- 관리 UI(`/`, `/projects`, `/advanced`, `/logs`, `/database`)는 localhost 전용으로 설계되어 있습니다. reverse proxy, ngrok, 포트포워딩 등으로 외부에 공개하지 마세요.
- Claude `--dangerously-skip-permissions`, Gemini `--approval-mode yolo`, Codex `danger-full-access` 같은 옵션은 로컬 파일을 수정할 수 있으므로 허용 프로젝트와 신뢰 사용자 범위를 제한한 뒤 사용하세요.
- 대화 기억 SQLite에는 사용자의 Telegram 요청과 Job 요약이 저장될 수 있습니다. 민감한 코드를 메시지에 붙여넣지 말고, 필요 시 `/clear memory` 또는 관리 UI 고급 설정으로 정리하세요.

취약점 제보와 공개 전 점검 절차는 [`SECURITY.md`](SECURITY.md)를 참고하세요.

## 사전 준비

- Python 3.11 이상 또는 Conda
- 프로젝트마다 Telegram Bot Token(BotFather)과 허용할 Chat ID(필수)·User ID(선택)
- HTTPS 터널 도구(개발용 예: ngrok)
- Claude Code CLI, Codex CLI, Gemini CLI 중 사용할 도구 1개 이상
- 대상 Git 프로젝트와 worktree를 둘 로컬 디렉터리

## 설치

아직 정식 공개 전 버전이며 현재 패키지 버전은 `v0.0.1`입니다.

소스 체크아웃에서 설치:

```bash
pipx install .
remote-coder --version
remote-coder serve
```

개발 중 editable 설치:

```bash
python -m pip install -e ".[dev]"
remote-coder serve --reload
```

서버만 직접 실행할 때는 다음 명령과 동일합니다.

```bash
uvicorn app.main:app
```

`remote-coder serve`는 서버 실행만 담당합니다. ngrok 실행과 Telegram webhook 등록까지 한 번에 처리하려면 기존 개발용 스크립트인 `./run.sh`를 사용하세요.

### 배포 패키지 빌드

```bash
python -m pip install build
python -m build
```

생성물은 `dist/remote_coder-0.0.1.tar.gz`와 `dist/remote_coder-0.0.1-py3-none-any.whl`입니다.

### Homebrew 배포

이 프로젝트는 CLI/서버 패키지이므로 macOS 앱 번들용 `brew install --cask remote-coder`보다 Formula 방식인 `brew install remote-coder`가 적합합니다. Formula 초안은 [`packaging/homebrew/remote-coder.rb`](packaging/homebrew/remote-coder.rb)에 있습니다.

릴리스 후 필요한 작업:

- `homepage`를 실제 저장소 URL로 교체
- PyPI 또는 GitHub Release의 `remote_coder-0.0.1.tar.gz` URL로 `url` 교체
- `shasum -a 256 dist/remote_coder-0.0.1.tar.gz` 값으로 `sha256` 교체
- Python 의존성 `resource` 블록은 `brew pypi-poet remote-coder` 같은 도구로 생성해 Formula에 추가

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

- 선택(초기 시드): `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_CHAT_IDS`, `TELEGRAM_ALLOWED_USER_IDS`, `TELEGRAM_WEBHOOK_SECRET` — 레지스트리가 비어 있을 때 첫 프로젝트 생성에만 쓰일 수 있습니다. 운영 설정은 관리 UI 또는 `projects.json`의 **프로젝트별** 필드를 우선합니다.
- 선택: `GIT_REMOTE_NAME` (기본 `origin`) — 커밋 후 push 및 `/rebase`, `/pr`, `/clear` 시 사용
- 선택: `PROJECTS_CONFIG_PATH` — 여러 Git 프로젝트 등록 파일(JSON 또는 `.yaml`) 경로
- 선택: `CONVERSATION_DB_PATH` — 프로젝트+채팅별 대화 기억 SQLite 경로 (미설정 시 `PROJECT_ROOT/.remote-coder/conversations.sqlite3`)
- 선택: `CONVERSATION_RECENT_LIMIT` — 모호한 후속 요청 시 runner에 붙이는 최근 기록 개수 (기본 `10`)
- 선택: `CODEX_SANDBOX` — Codex `codex exec --sandbox` 값 (`read-only`, `workspace-write`, `danger-full-access`). 기본 `workspace-write`(Job worktree에서 파일 수정 가능)
- 선택: Gemini 사용 시 `npm install -g @google/gemini-cli`로 Gemini CLI를 설치하고 `gemini` 명령이 PATH에 잡히도록 설정
- 초기 시드(1회용): `DEFAULT_PROJECT`, `PROJECT_ROOT`, `WORKTREE_BASE_DIR`

기존 단일 `.env`만 쓰던 경우 → 관리 UI에서 각 프로젝트에 `bot_token`·allowlist를 옮기거나, 시드 생성 후 `.env`의 민감 값을 정리하는 것을 권장합니다. [`docs/multi-bot-setup.md`](docs/multi-bot-setup.md) 마이그레이션 절을 참고하세요.

## 2.5) 로컬 관리 UI (프로젝트 등록)

서버를 띄운 뒤 **같은 머신**에서 브라우저로 접속합니다.

- 관리 허브: `http://127.0.0.1:8000/` (요약·다른 페이지로 이동)
- 프로젝트 등록: `http://127.0.0.1:8000/projects` (목록, 추가·수정·삭제, 폴백 기본값, **봇 토큰·allowlist·webhook secret**, 봇별 webhook 경로 표시. `./run.sh` 실행 중에는 등록·수정한 활성 프로젝트의 Telegram webhook과 `/` 명령어 메뉴도 즉시 갱신)
- 고급 설정: `http://127.0.0.1:8000/advanced`
- 서버 로그: `http://127.0.0.1:8000/logs` (`app` 로거 기준 인메모리 링 버퍼, 자동 새로고침·카테고리·`chat_id`/`job_id` 필터)
- 데이터 조회: `http://127.0.0.1:8000/database` (대화 기억 SQLite 테이블 조회·CSV보내기)
- 자연어 작업 대상 프로젝트는 **해당 봇에 고정**되어 있습니다. `project:` 토큰은 지원하지 않습니다.
- `PROJECTS_CONFIG_PATH`가 없으면 기본 경로 `PROJECT_ROOT/.remote-coder/projects.json`을 사용합니다.
- 레지스트리 파일이 없으면 `.env`의 초기 시드 값(`DEFAULT_PROJECT`, `PROJECT_ROOT`, `WORKTREE_BASE_DIR`)으로 자동 생성됩니다.

### 서버 로그(이벤트) 로거 네임 규약

관리 UI `/logs`와 API `GET /api/logs`에 쌓이는 항목은 `app` 패키지 로거로 기록됩니다. 주요 로거 이름과 용도는 다음과 같습니다.

| 로거 이름 | 용도 |
|-----------|------|
| `app.telegram.inbound` | Webhook 수신·빈 메시지 스킵 |
| `app.telegram.outbound` | `sendMessage` 성공/실패, Job 접수·결과 알림 발송 |
| `app.telegram.command` | 슬래시 명령 처리, 자연어 Job 접수, `/init`·`/clear` 확인 등 상태 변경 |
| `app.security.auth` | Webhook secret 불일치, allowlist 거부 |
| `app.jobs.lifecycle` | Job 제출·단계(`git_worktree`/`runner`/…)·성공·실패 |
| `app.git.service` | worktree 생성·커밋·push·정리·rebase 통합 등 Git Adapter |
| `app.ai.claude` / `app.ai.codex` / `app.ai.gemini` | Runner 시작·종료·timeout |

구조화 필드(`category`, `chat_id`, `user_id`, `project`, `job_id`)는 UI 필터·배지로 조회할 수 있습니다. 코드에서는 `app.monitoring.events.EventLogger`와 `app.monitoring.log_buffer.LOG_RECORD_CONTEXT_KEYS` 화이트리스트를 사용합니다.

### 고급 설정 (위험 옵션)

관리 UI의 **고급 설정** 페이지(`http://127.0.0.1:8000/advanced`)에서 전역 설정 파일 `PROJECT_ROOT/.remote-coder/advanced_settings.json`을 읽고 저장할 수 있습니다. 기본값은 모두 꺼져 있으며, 켜지 않으면 기존 동작과 동일합니다. 예전 버전에서만 쓰이던 키는 로드 시 무시됩니다(예: 제거된 `auto_pull_on_project_switch`).

> [!WARNING]
> “요청 결과를 즉시 main/master에 반영 후 push” 옵션은 AI가 만든 변경을 통합 브랜치에 자동 반영합니다. 개인 실험용 저장소가 아니라면 기본값(off)을 유지하고, 사용 전 원격 브랜치 보호와 백업 정책을 확인하세요.

- **요청 결과를 즉시 main/master에 반영 후 push**: Job이 변경을 커밋·브랜치 push까지 성공하면, `/rebase`와 유사하게 해당 브랜치를 통합 브랜치(`main` 또는 `master`)에 fast-forward 병합한 뒤 원격에 push합니다. 충돌·non-ff 등으로 통합에 실패하면 Job은 실패로 기록됩니다.
- **SQLite 대화 기억 저장량 제한**: 켜면 `conversation_entries` 테이블 전체를 대상으로, 오래된 행부터 삭제합니다. **최대 행 수**와 **최대 DB 용량(bytes)** 중 하나 이상을 양수로 지정해야 하며, 둘 다 지정하면 행 수 제한을 먼저 맞춘 뒤 용량 제한을 맞추기 위해 삭제·`VACUUM`을 반복합니다. `message_branch_links`는 고아 링크를 정리합니다.

## 3) 한 번에 실행하기 (권장)

미리 작성된 실행 스크립트를 사용하면 Conda 환경 활성화, ngrok 실행, Webhook 등록, 서버 실행을 모두 한 번에 처리합니다. `./run.sh`는 ngrok 공개 URL을 `TELEGRAM_WEBHOOK_PUBLIC_BASE_URL`로 서버에 전달하므로, 서버를 재시작하지 않아도 관리 UI에서 등록·수정한 활성 프로젝트의 Telegram webhook과 `/` 명령어 메뉴가 즉시 갱신됩니다. 멀티봇은 공개 HTTPS Base URL만 넘겨 활성 프로젝트마다 webhook과 명령어 메뉴를 등록하는 `python scripts/set_webhook.py <URL>` 을 사용할 수도 있습니다.

```bash
./run.sh
```

Windows PowerShell에서는 다음 스크립트를 사용할 수 있습니다.

```powershell
.\run.ps1
```

또는 PowerShell 실행 정책을 자동 우회하는 배치 래퍼를 사용할 수 있습니다.

```bat
run.bat
```

Windows 실행 전에는 `ngrok.exe`가 설치되어 있고 PATH에서 실행 가능해야 합니다. 확인:

```powershell
ngrok version
```

- 스크립트 실행 후 텔레그램에서 바로 봇에게 말을 걸면 동작합니다.
- 서버를 종료하려면 `Ctrl+C`를 누르면 ngrok도 함께 종료됩니다.

## 4) 지원 명령어 (MVP)

`./run.sh` 또는 `python scripts/set_webhook.py <URL>` 로 Telegram 등록을 갱신하면 BotFather에서 설정하는 것과 같은 `/` 명령어 메뉴가 각 프로젝트 봇에 등록됩니다.

- `/start` : 인라인 메뉴 허브 (모델·모니터·정리·관리 항목별 버튼 바로가기)
- `/help` : 명령어 도움말 (model·monitor·clear 항목별 인라인 버튼 제공)
- `/model` : 기본 모델 확인 (인라인 버튼으로 선택)
- `/model claude` : 현재 chat의 기본 모델을 claude로 변경
- `/model codex` : 현재 chat의 기본 모델을 codex로 변경
- `/model gemini` : 현재 chat의 기본 모델을 gemini로 변경
- `/status` : 최근 Job 목록에서 인라인 버튼으로 선택
- `/status <job_id>` : 작업 상태 조회
- `/init` : 이 채팅의 기본 모델 오버라이드·`/clear` 및 자연어 Job 확인 대기 상태를 초기화(봇에 묶인 프로젝트는 변하지 않음; SQLite·Git은 변경 없음)
- `/reports` : 현재 채팅·현재 작업 프로젝트 기준으로 SQLite 대화 기억을 SQL 집계해 요약 리포트
- `/branch` : 이 채팅 **적용 프로젝트** 저장소의 현재 checkout 브랜치 표시
- `/branch <이름>` : 적용 프로젝트에서 로컬 브랜치가 있을 때만 `git switch` (없으면 오류, 원격만 있는 브랜치는 자동 생성하지 않음)
- `/pull` : 원격 저장소의 모든 브랜치 정보를 가져오고(fetch), 현재 브랜치를 pull 합니다. 체크아웃되지 않은 다른 로컬 브랜치(main 포함)들에 대해서도 fast-forward 업데이트를 시도합니다.
- `/rebase` : 인라인 버튼으로 로컬과 원격에 모두 있는 브랜치 선택 (main/master 제외) 후 `main`(또는 `master`) 기준으로 rebase → fast-forward 병합 → 원격 push
- `/rebase <branch>` : 직접 브랜치를 지정해 rebase
- `/pr` : 인라인 버튼으로 로컬 브랜치 선택 후 GitHub Pull Request 생성. PR 본문에는 해당 브랜치 작업 시 주고받은 요청과 AI 결과가 포함됩니다. GitHub CLI(`gh`)가 필요합니다 (`gh auth login`).
- `/pr <branch>` : 직접 브랜치를 지정해 PR 생성
- `/clear branch` : **이 봇에 묶인 프로젝트**에서만 `remote-*` 로컬·원격 브랜치와 연결된 linked worktree 정리
- `/clear worktrees` : **이 봇 프로젝트**의 관리 대상 worktree 정리 + stale entry prune
- `/clear memory` : **이 봇 프로젝트 + 현재 채팅**의 대화 기억(SQLite)만 삭제
- `/stop` : 진행 중인 Job 목록에서 인라인 버튼으로 선택해 중단
- `/stop <job_id>` : 지정한 Job 강제 중단 (queued/running 상태만 가능)
- `/monitor model` : 현재 채팅 기본 모델 기준 Claude(`claude auth status`) / Codex(`codex --version`) / Gemini(`gemini --version`) 등 CLI Probe + 로컬 CLI 로그에서 관측한 실제 사용량 요약. Codex 세션 로그에 `rate_limits`가 있으면 5시간/주간 잔여율과 리셋 시각도 표시하고, Claude/Gemini는 로컬 transcript/chat 로그의 세부 모델·토큰·요청 수를 표시합니다.
- `/monitor memory` : 이 채팅·현재 **적용 프로젝트** 기준 SQLite 대화 기억 행 수·역할별 행 수·DB 파일 크기
- `/monitor branch` : 적용 프로젝트 저장소의 브랜치 요약(로컬/원격 개수 및 목록)
- `/monitor worktrees` : linked worktree 목록·detached 개수·Remote Coder managed 후보 요약
- `/monitor code` : 적용 프로젝트 루트 기준 코드 파일 수·줄 수 추정(확장자 화이트리스트, `.git`·`node_modules` 등 제외)
- `/monitor project` : **이 봇에 묶인** 프로젝트 레코드 요약(이름, 활성 여부, 경로, 기본 모델, worktree 디렉터리)
- 자연어 메시지: 현재 프로젝트·작업 브랜치·사용 모델 확인 후 `y`/`Y` 입력 시 AI 작업 요청 생성

참고:

- `/model`로 채팅별로 덮어쓴 기본 모델은 인메모리입니다. 서버 재시작 시 레지스트리의 프로젝트 `default_model`로 돌아갑니다.
- **적용 프로젝트는 항상 이 봇 인스턴스에 바인딩된 이름**입니다. **`/branch`, `/rebase`, `/monitor memory|branch|worktrees|code|project` 등은 그 저장소를 기준으로 동작합니다.**
- `/init`으로 채팅별 모델 오버라이드와 확인 대기 상태를 되돌릴 수 있습니다(대화 기억 SQLite·Git 저장소는 건드리지 않음).
- AI Job은 **요청에 사용된 프로젝트 저장소**의 **현재 `HEAD` 커밋**에서 detached worktree를 만든 뒤 실행합니다. **워킹 트리에 변경이 있을 때만** 작업 브랜치를 만들고 커밋합니다. 커밋이 있으면 `GIT_REMOTE_NAME`(기본 `origin`)으로 push합니다. 저장소 브랜치를 바꾸려면 먼저 `/branch <이름>`으로 로컬 브랜치를 전환하세요.
- 자동 생성 커밋 메시지는 다음 형식을 사용합니다.

  ```text
  type: title
  - contents1
  - contents2

  committed by remote-coder: job-id
  ```

  `title`은 기능 수정 내용을 한 줄로 요약하고, 첫 번째 본문 항목은 사용자 원문이나 최근 수정 파일 목록이 아니라 AI Agent가 수행한 변경 내용을 설명합니다. 변경 파일 목록은 Job 결과 알림에서 별도로 확인합니다.

- 자연어 메시지에서 `model: codex`, `model: gemini`, `branch: my-branch`, `no commit` 토큰을 함께 사용할 수 있습니다. (`branch:` 값은 `/branch`와 동일 규칙으로 검증됩니다.)
- 자연어 요청은 파싱 후 바로 실행되지 않습니다. 봇이 확인 메시지에 현재 프로젝트, 작업 브랜치, 사용 모델을 표시하며 `y` 또는 `Y`를 입력해야 Job이 생성됩니다.
- **대화 기억(SQLite)**: 같은 텔레그램 채팅·같은 작업 프로젝트 기준으로 사용자 메시지와 Job 접수/결과 요약이 SQLite에 쌓입니다. 서버를 재시작해도 유지됩니다. 이전에 구체적인 지시를 보낸 뒤 `작업 시작해줘`, `진행해줘`, `그거 해줘`, `시작해줘`처럼 짧은 후속 문장만내면, 최근 기록을 합쳐 AI 지시문으로 만듭니다. 맥락이 없으면 봇이 안내 메시지를 보냅니다.
- **Reply 체인**: 이전 메시지에 답장(reply)으로 보낸 자연어 요청마다, SQLite에 남은 조상 메시지들의 본문과 각 메시지에 연결된 Job 결과 요약을 `[Reply 체인 맥락]` 블록으로 Codex/Claude instruction 앞에 붙입니다. (봇이 해당 메시지를 수신·저장한 경우에만 복원됩니다.)
- `/reports 7`처럼 최근 표시 개수를 함께 줄 수 있습니다. 허용 범위는 `1~10`이며, 기본값은 `5`입니다.
- worktree 생성 직후 쓰기 가능 여부를 점검합니다. AI 출력에 읽기 전용·수정 불가 등의 표현이 있고 Git 변경이 없으면 성공이 아니라 **실패**로 처리됩니다.
- 작업 완료/실패 메시지에는 AI 실행 결과 요약(`stdout`/`stderr`)이 함께 포함됩니다.
- 전체 출력 원문은 worktree 로그 파일(`WORKTREE_BASE_DIR/_logs/<job_id>.log`)에서 확인할 수 있습니다.

## 5) 모델별 사용 가이드

- 멀티봇·Webhook·마이그레이션: [`docs/multi-bot-setup.md`](docs/multi-bot-setup.md)
- Claude 사용자: [`docs/claude-guide.md`](docs/claude-guide.md)
- Codex 사용자: [`docs/codex-guide.md`](docs/codex-guide.md)
- Gemini 사용자: [`docs/gemini-guide.md`](docs/gemini-guide.md)
- Worktree가 read-only로 실패할 때: [`docs/read-only-workspace.md`](docs/read-only-workspace.md)

## 6) 테스트

멀티봇 라우팅·알림 격리·프로젝트 스코프 상태는 `tests/test_webhook_multibot.py`, `tests/test_bot_instance_manager.py`, `tests/test_project_scoped_state.py` 등에서 다룹니다.

```bash
conda activate remote-coder
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q -p pytest_asyncio.plugin -p respx.fixtures
```

## 7) 공개 저장소 관리

- 라이선스: [Apache License 2.0](LICENSE)
- 기여 방법: [CONTRIBUTING.md](CONTRIBUTING.md)
- 보안 정책: [SECURITY.md](SECURITY.md)
- Pull Request 전에는 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 conda run -n remote-coder pytest -q -p pytest_asyncio.plugin -p respx.fixtures`를 실행해 주세요.
