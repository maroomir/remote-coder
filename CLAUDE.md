# Remote AI Coder — CLAUDE.md

텔레그램 메시지로 로컬 AI 코딩 도구(Claude Code / Codex / Gemini CLI)를 원격 실행하고, 결과를 Git 브랜치/커밋으로 관리하는 FastAPI 기반 자동화 시스템입니다.

## 핵심 흐름

```
Telegram Message → FastAPI Webhook → Auth → Job Manager
  → Git Worktree → AI Runner (Claude/Codex/Gemini)
  → Git Commit → Telegram Notification
```

## 디렉토리 구조

```
app/
  main.py                     # FastAPI 앱 생성
  config.py                   # 환경 변수 중앙 관리
  models.py                   # 공통 데이터 모델
  telegram/
    webhook.py                # Webhook 라우터
    notifier.py               # Telegram 메시지 발송
    commands.py               # /help, /model, /status 등 명령 처리
    parser.py                 # 메시지 파싱
    conversation.py           # 대화 컨텍스트 (SQLite)
    confirmations.py          # 사용자 확인 흐름
    model_preferences.py      # 모델 선택 상태 관리
    project_preferences.py    # 프로젝트 선택 상태 관리
  jobs/
    manager.py                # Job 생성/실행/상태 변경 (Facade)
    store.py                  # Job 저장소
    schemas.py                # Job 모델 (queued/running/succeeded/failed/cancelled)
  git/
    service.py                # Git/worktree 조작
    branch_naming.py          # 브랜치명 생성 정책
    commit_message.py         # 커밋 메시지 포맷
    ai_commit.py              # AI 실행 후 커밋 오케스트레이션
  ai/
    base.py                   # AiRunner 인터페이스 (Strategy)
    claude.py                 # Claude Code Runner
    codex.py                  # Codex Runner
    gemini.py                 # Gemini Runner
    factory.py                # Runner 생성 Factory
  projects/
    registry.py               # 프로젝트 경로/설정 관리
  security/
    auth.py                   # allowlist 검증
  monitoring/
    log_buffer.py             # 인메모리 링 버퍼 + MemoryLogHandler
    events.py                 # EventLogger Facade
    model.py / git.py / code.py / memory.py
  admin/
    router.py                 # 관리 UI 라우터
    database_browser.py       # SQLite 브라우저
    advanced_settings.py      # 고급 설정 UI
tests/
```

## 개발 환경

- Python 3.11, Conda 환경명: `remote-coder`
- 테스트: `conda run -n remote-coder pytest -q`
- 서버 실행: `conda run -n remote-coder uvicorn app.main:app --reload`
- 환경 변수: `.env` (예시: `.env.example`) — **절대 코드에 하드코딩 금지**

## 아키텍처 원칙

- **OOP + GoF 패턴 우선**: 변경 가능성이 큰 부분은 Strategy/Factory/Adapter/Command 패턴 적용
  - AI Runner 선택 → Strategy + Factory (`app/ai/factory.py`)
  - 외부 CLI 호출 → Adapter 계층에 격리
  - 텔레그램 명령어 → Command 패턴 (`app/telegram/commands.py`)
  - Job 실행 흐름 → Facade (`app/jobs/manager.py`)
- **단일 책임**: 클래스/모듈 변경 이유를 하나로 유지
- **Webhook은 즉시 응답**: 장시간 AI 작업은 반드시 백그라운드 Job으로 분리
- **미니멀 주석**: 주석은 Why·보안·제약·트레이드오프·워크어라운드만 남기고, 시그니처와 동어반복인 docstring은 추가하지 않음. 마커는 `TODO(#)`, `FIXME(#)`, `NOTE:`, `SECURITY:`만 사용. 자세한 기준은 `.cursor/rules/60-comments-policy.mdc` 참조.

## Git/Worktree 규칙

- AI 작업은 항상 별도 worktree에서 실행 (기본 브랜치/checkout 브랜치 직접 수정 금지)
- worktree는 요청 프로젝트 저장소의 현재 HEAD에서 생성
- 변경 사항이 없으면 브랜치 생성/커밋/push 금지
- 변경 사항이 있으면 브랜치 생성 → 커밋 → `origin` push
- 커밋 메시지 형식: `type: title` + bullet 목록 + `committed by remote-coder: <job-id>`
  - `title`은 기능 수정 내용 한 줄 요약 (사용자 원문 그대로 쓰지 않음)
  - 첫 bullet은 AI가 실제로 수행한 변경 내용 설명
- Job 결과에 commit hash, branch name, changed files 저장

## AI Runner 규칙

- 공통 `AiRunner` 인터페이스: 입력(지시문, cwd, timeout, env) → 출력(stdout, stderr, exit_code, 시작/종료 시각)
- subprocess 호출: `shell=True` 금지, 리스트 기반 args 사용, timeout/cwd 명시
- Runner 구현은 `app/ai/` 에 격리, 도메인 로직이 CLI 세부사항에 의존하지 않도록

## 보안 규칙 (필수)

- Bot Token, API Key, Chat ID를 코드에 하드코딩 금지
- 사용자 메시지를 shell 명령으로 직접 실행 금지
- 허용된 Chat ID/User ID만 처리 (`app/security/auth.py`)
- 등록된 프로젝트 경로 밖에서 Git/AI 작업 실행 금지
- AI 결과는 별도 브랜치에만 커밋, 자동 배포 금지
- 관리 UI 로그: 사용자 메시지 원문 금지, 첫 줄 80자 프리뷰만 허용
  - `chat_id`, `job_id` 등은 `logging extra`로만 전달 (`LOG_RECORD_CONTEXT_KEYS` 준수)

## 이벤트 로그

구조화 로그는 반드시 `app.monitoring.events.EventLogger`를 사용합니다.

```python
from app.monitoring.events import EventLogger
logger = EventLogger("app.telegram.webhook")
logger.info("message", extra={"chat_id": ..., "job_id": ...})
```

## 테스트 기준

- 우선 테스트 대상: 명령 파싱, 인증, Job 상태 전이, Git 서비스, AI Runner 성공/실패
- 외부 API(Telegram, Claude CLI, Git)는 mock 처리
- 실제 저장소 수정, 외부 네트워크 호출은 기본 테스트에서 수행 금지
- Strategy/Command/Adapter 패턴 객체는 독립 단위 테스트 필수

## Telegram 명령어 규칙

- 선택지가 있는 명령 (`/model`, `/status`, `/project`, `/branch`, `/rebase`, `/stop`): 인자 없이 호출 시 인라인 버튼 우선 제공
- 인라인 버튼 callback data는 기존 슬래시 명령 경로로 처리
- `/init`: 채팅의 적용 프로젝트·기본 모델·확인 대기 상태를 초기화 (SQLite·Git 저장소 변경 없음)

## 규칙 문서 위치

| 문서 | 역할 |
|---|---|
| `PLAN.md` | 제품 기획, 요구사항, 로드맵 |
| `.clinerules/` | Cline용 주제별 개발 규칙 |
| `.cursor/rules/` | Cursor용 동일 규칙 (.mdc) |
| `AGENTS.md` | AI 에이전트 작업 절차/체크리스트 |
| `CLAUDE.md` | Claude Code용 작업 컨텍스트 (이 파일) |

규칙 문서 간 충돌 시 임의 판단 말고 사용자에게 확인합니다.
