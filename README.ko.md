# Remote AI Coder

Telegram 메시지 하나로 내 로컬 개발 머신의 Claude Code, Codex, Gemini를 실행합니다. Remote AI Coder는 요청마다 Git worktree를 분리하고, 결과를 별도 브랜치에 커밋한 뒤 Telegram으로 알려줍니다.

*English: [README.md](README.md) · 한국어: 이 문서*

> [!WARNING]
> 이 도구는 AI CLI, Git, 로컬 파일 시스템에 접근하는 로컬 자동화 도구입니다. 개인 환경에서만 사용하고, Telegram allowlist를 설정하며, 서버와 관리 UI를 공개 인터넷에 노출하지 마세요.

## 핵심 기능

- Telegram을 로컬 코딩 에이전트용 가벼운 원격 컨트롤러로 사용합니다.
- 등록 프로젝트마다 별도 Telegram 봇, allowlist, 설정을 둡니다.
- 요청별 Git worktree, 브랜치 생성, 커밋, push, 결과 알림을 처리합니다.
- Claude, Codex, Gemini를 같은 Job 흐름으로 실행합니다.
- 답장(reply)으로 연결된 Job은 동일한 AI CLI 세션을 이어가며 이전 맥락 위에서 작업합니다.
- 프로젝트 설정, 고급 옵션, 로그, 대화 기억을 로컬 관리 UI에서 확인합니다.
- 커밋 없이 분석만 하는 읽기 전용 `plan:` / `ask:` / `research:` 모드를 지원합니다. PLAN 모드는 결정이 필요한 선택지를 인라인 버튼으로 먼저 묻고, 답을 반영해 최종 계획을 완성합니다. RESEARCH 모드는 유용할 때 선택된 AI CLI가 인터넷 검색을 사용하도록 지시합니다.

## 빠른 시작

CLI를 설치합니다.

```bash
pip install remote-coder
```

첫 패키지 릴리스 전에는 소스에서 설치합니다.

```bash
pip install git+https://github.com/maroomir/remote-coder.git
```

로컬 도구를 점검하고 한 번에 실행합니다.

```bash
remote-coder doctor
remote-coder up
```

`http://127.0.0.1:8000/`을 열어 첫 프로젝트를 등록한 뒤, Telegram에서 해당 프로젝트 봇에게 메시지를 보내면 됩니다. `remote-coder up`은 서버 실행, ngrok 터널, webhook 등록, Telegram 명령어 메뉴 갱신을 함께 처리합니다. 로컬 서버만 띄우려면 `remote-coder up --no-tunnel`을 사용하세요.

## 준비물

- Python 3.11 이상
- Telegram webhook용 `ngrok` 또는 HTTPS 터널
- 프로젝트마다 하나의 Telegram bot token
- 허용할 Telegram Chat ID, 필요하면 User ID
- 로컬 AI CLI 중 하나 이상: `claude`, `codex`, `gemini`
- 자동화할 로컬 Git 저장소
- `/pr` 사용 시 `gh auth login`으로 인증된 GitHub CLI(`gh`)

## 동작 방식

```text
Telegram message
 -> FastAPI webhook /telegram/webhook/{sha256-prefix16}
 -> 프로젝트에 묶인 봇 인스턴스와 allowlist 검사
 -> 명령 파서 또는 자연어 확인
 -> JobManager
 -> Git worktree
 -> Claude / Codex / Gemini runner
 -> branch, commit, push, Telegram 결과 알림
```

각 프로젝트는 자기 Telegram 봇을 갖습니다. Webhook 경로에는 원본 토큰이 아니라 `SHA-256(bot token)`의 앞 16자리 16진 문자열만 들어갑니다. 자연어 Job은 실행 전에 대상 프로젝트, 브랜치, 모델, 모드를 보여주고 확인을 받은 뒤 시작합니다.

## 자주 쓰는 명령

| 명령 | 용도 |
|---|---|
| `/start`, `/help` | 메뉴 또는 도움말 열기 |
| `/model` | 현재 채팅의 기본 모델 확인/변경 |
| `/status [job_id]` | 최근 Job 또는 특정 Job 상태 조회 |
| `/branch [name]` | 바인딩된 프로젝트의 로컬 브랜치 확인/전환 |
| `/pull` | 원격 fetch 및 현재 브랜치 pull |
| `/rebase [branch]` | 완료 브랜치를 `main` 또는 `master`에 rebase 후 fast-forward |
| `/pr [branch]` | 성공한 Job 브랜치에서 `gh`로 GitHub PR 생성 |
| `/fix ...` | 이전 Job의 커밋 메시지 또는 소스 재작업 |
| `/monitor ...` | 모델, 메모리, 브랜치, worktree, 코드, 프로젝트 상태 확인 |
| `/clear ...` | 관리 대상 브랜치, worktree, 대화 기억 정리 |
| `/stop [job_id]` | 대기/실행 중인 Job 취소 |
| `/init` | 채팅 로컬 모델과 확인 대기 상태 초기화 |

브랜치 없이 `/pr`를 실행하면 현재 프로젝트와 Telegram 채팅에서 성공한 Job이 만든 브랜치 중 설정된 Git 원격에 남아 있는 브랜치만 표시합니다. `/pr <branch>` 직접 호출도 같은 소유 범위를 검사하고 원격 브랜치가 아직 존재하는지 다시 확인합니다. 이 명령을 사용하기 전에 [GitHub CLI](https://cli.github.com/)를 설치하고 `gh auth login`을 실행하세요.

자연어 예시:

```text
로그인 검증 버그를 model: codex로 고쳐줘
plan: 마이그레이션 전에 위험 요소만 정리해줘
/ask 이 저장소의 테스트 명령이 뭐야?
/research Telegram webhook 보안 권장사항을 최신 기준으로 비교해줘
수정: 방금 작업에서 README 문구만 더 간결하게 바꿔줘
```

## 설정

일상적인 설정은 로컬 관리 UI에서 처리합니다. 파일은 기본적으로 `~/.remote-coder` 아래에 저장됩니다.

- `projects.json`: 프로젝트, bot token, allowlist, root path, 기본 모델
- `advanced_settings.json`: timeout, sandbox, 언어, worktree 보존, 메모리 제한 등 전역 동작
- `worktrees/<project>/`: 관리되는 Job worktree와 로그
- 서버 시작 시 SQLite에 남은 `queued` Job은 재실행하고, 서버 종료 시점에 `running`이던 Job은 `/status`에서 확인할 수 있도록 `server_restart` 실패로 정리합니다.

주요 오버라이드 환경변수는 `REMOTE_CODER_HOME`, `PROJECTS_CONFIG_PATH`, `CONVERSATION_DB_PATH`, `JOB_DB_PATH`입니다.

## 보안 메모

- `~/.remote-coder/projects.json`은 secret처럼 다루세요. Bot token은 평문으로 저장됩니다.
- 관리 UI는 localhost에서만 사용하세요.
- Telegram 메시지에 secret이나 민감한 코드를 붙여넣지 마세요.
- Claude `--dangerously-skip-permissions`, Gemini `--approval-mode yolo`, Codex `danger-full-access` 같은 위험 모드는 로컬 파일을 수정할 수 있습니다.
- 배포, 공개, 공유 전에 [`SECURITY.md`](SECURITY.md)를 확인하세요.

## 더 읽기

- 멀티봇 설정과 마이그레이션: [`docs/multi-bot-setup.ko.md`](docs/multi-bot-setup.ko.md)
- AI 러너: [`docs/ai-runners.ko.md`](docs/ai-runners.ko.md)
- Read-only worktree 문제 해결: [`docs/read-only-workspace.ko.md`](docs/read-only-workspace.ko.md)
- 기여 안내: [`CONTRIBUTING.md`](CONTRIBUTING.md)

## 개발

```bash
conda env create -f environment.yml
conda activate remote-coder
python -m pip install -e ".[dev]"
remote-coder up --no-tunnel --reload
```

테스트 실행:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 conda run -n remote-coder pytest -q -p pytest_asyncio.plugin -p respx.fixtures
```

라이선스: [Apache License 2.0](LICENSE)
