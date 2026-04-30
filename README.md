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
- 필요 시 `TELEGRAM_WEBHOOK_SECRET`
- 선택: `GIT_REMOTE_NAME` (기본 `origin`) — 커밋 후 push 및 `/rebase`, `/clear` 시 사용
- 선택: `PROJECTS_CONFIG_PATH` — 여러 Git 프로젝트 등록 파일(JSON 또는 `.yaml`) 경로
- 선택: `CONVERSATION_DB_PATH` — 프로젝트+채팅별 대화 기억 SQLite 경로 (미설정 시 `PROJECT_ROOT/.remote-coder/conversations.sqlite3`)
- 선택: `CONVERSATION_RECENT_LIMIT` — 모호한 후속 요청 시 runner에 붙이는 최근 기록 개수 (기본 `10`)
- 선택: `CODEX_SANDBOX` — Codex `codex exec --sandbox` 값 (`read-only`, `workspace-write`, `danger-full-access`). 기본 `workspace-write`(Job worktree에서 파일 수정 가능)
- 초기 시드(1회용): `DEFAULT_PROJECT`, `PROJECT_ROOT`, `WORKTREE_BASE_DIR`

## 2.5) 로컬 관리 UI (프로젝트 등록)

서버를 띄운 뒤 **같은 머신**에서 브라우저로 접속합니다.

- URL: `http://127.0.0.1:8000/`
- 등록된 프로젝트 목록, 추가·수정·삭제, 기본 프로젝트 지정
- 자연어 요청에서 `project: 프로젝트이름` 으로 대상을 바꿀 수 있습니다. 생략 시에는 텔레그램 채팅에서 `/project`로 선택한 작업 프로젝트가 있으면 그것을, 없으면 레지스트리의 기본 프로젝트가 사용됩니다.
- `PROJECTS_CONFIG_PATH`가 없으면 기본 경로 `PROJECT_ROOT/.remote-coder/projects.json`을 사용합니다.
- 레지스트리 파일이 없으면 `.env`의 초기 시드 값(`DEFAULT_PROJECT`, `PROJECT_ROOT`, `WORKTREE_BASE_DIR`)으로 자동 생성됩니다.

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
- `/projects` : 등록 프로젝트 목록 및 이 채팅의 현재 적용 프로젝트
- `/project` : 이 채팅의 현재 작업 프로젝트(인메모리) 확인
- `/project <이름>` : 이 채팅의 작업 프로젝트를 등록된 이름으로 전환(인메모리, 레지스트리 기본값은 변경하지 않음)
- `/reports` : 현재 채팅·현재 작업 프로젝트 기준으로 SQLite 대화 기억을 SQL 집계해 요약 리포트
- `/branches` : 기본 프로젝트 저장소의 로컬·원격(`GIT_REMOTE_NAME`) 브랜치 목록
- `/branch` : 기본 프로젝트 저장소의 현재 checkout 브랜치 표시
- `/branch <이름>` : 기본 프로젝트에서 로컬 브랜치가 있을 때만 `git switch` (없으면 오류, 원격만 있는 브랜치는 자동 생성하지 않음)
- `/rebase` 또는 `/rebase <branch>` : 기본 프로젝트에서 해당 브랜치를 `main`(또는 `master`) 기준으로 rebase한 뒤 `main`에 fast-forward 병합 후 원격에 push (인자 생략 시 이 채팅의 최근 성공 Job 브랜치)
- `/clear branch` : 등록된 enabled 프로젝트마다 `remote-*` 로컬·원격 브랜치와 연결된 linked worktree 정리
- `/clear worktrees` : 등록된 enabled 프로젝트마다 관리 대상 worktree(`WORKTREE_BASE_DIR` 하위 및 `remote-*` checkout linked worktree) 정리 + stale entry prune
- `/clear memory` : 대화 기억 SQLite 데이터베이스 초기화
- 자연어 메시지: AI 작업 요청 생성

참고:

- `/model`로 변경한 기본 모델은 MVP에서는 인메모리 저장입니다. 서버 재시작 시 초기화됩니다.
- `/project`로 선택한 작업 프로젝트도 채팅별 인메모리이며, 서버 재시작 시 초기화됩니다. `project:` 옵션이 있으면 그 값이 우선합니다.
- AI Job은 기본 프로젝트 **현재 `HEAD` 커밋**에서 detached worktree를 만든 뒤 실행합니다. **워킹 트리에 변경이 있을 때만** 작업 브랜치를 만들고 커밋합니다. 커밋이 있으면 `GIT_REMOTE_NAME`(기본 `origin`)으로 push합니다. 저장소 브랜치를 바꾸려면 먼저 `/branch <이름>`으로 로컬 브랜치를 전환하세요.
- 자동 생성 커밋 메시지는 다음 형식을 사용합니다.

  ```text
  type: title
  - contents1
  - contents2

  committed by remote-coder:job-id
  ```

- 자연어 메시지에서 `model: codex`, `branch: my-branch`, `project: 등록이름`, `no commit` 토큰을 함께 사용할 수 있습니다. (`branch:` 값은 `/branch`와 동일 규칙으로 검증됩니다.)
- **대화 기억(SQLite)**: 같은 텔레그램 채팅·같은 작업 프로젝트 기준으로 사용자 메시지와 Job 접수/결과 요약이 SQLite에 쌓입니다. 서버를 재시작해도 유지됩니다. 이전에 구체적인 지시를 보낸 뒤 `작업 시작해줘`, `진행해줘`, `그거 해줘`, `시작해줘`처럼 짧은 후속 문장만내면, 최근 기록을 합쳐 AI 지시문으로 만듭니다. 맥락이 없으면 봇이 안내 메시지를 보냅니다.
- **Reply 체인**: 이전 메시지에 답장(reply)으로 보낸 자연어 요청마다, SQLite에 남은 조상 메시지들의 본문과 각 메시지에 연결된 Job 결과 요약을 `[Reply 체인 맥락]` 블록으로 Codex/Claude instruction 앞에 붙입니다. (봇이 해당 메시지를 수신·저장한 경우에만 복원됩니다.)
- `/reports 7`처럼 최근 표시 개수를 함께 줄 수 있습니다. 허용 범위는 `1~10`이며, 기본값은 `5`입니다.
- worktree 생성 직후 쓰기 가능 여부를 점검합니다. AI 출력에 읽기 전용·수정 불가 등의 표현이 있고 Git 변경이 없으면 성공이 아니라 **실패**로 처리됩니다.
- 작업 완료/실패 메시지에는 AI 실행 결과 요약(`stdout`/`stderr`)이 함께 포함됩니다.
- 전체 출력 원문은 worktree 로그 파일(`WORKTREE_BASE_DIR/_logs/<job_id>.log`)에서 확인할 수 있습니다.

## 5) 모델별 사용 가이드

- Claude 사용자: [`docs/claude-guide.md`](docs/claude-guide.md)
- Codex 사용자: [`docs/codex-guide.md`](docs/codex-guide.md)
- Worktree가 read-only로 실패할 때: [`docs/read-only-workspace.md`](docs/read-only-workspace.md)

## 6) 테스트

```bash
conda activate remote-coder
pytest -q
```
