# 텔레그램 기반 원격 AI 코딩 자동화 시스템 기획서

## 1. 문서 개요

본 문서는 텔레그램 메시지를 통해 로컬 개발 머신의 AI 코딩 도구를 원격으로 실행하고, 작업 결과를 Git 브랜치와 커밋으로 관리하는 **Remote AI Coder** 프로젝트의 초기 기획서입니다.

프로젝트 착수 전 제품 방향, 범위, 핵심 기능, 아키텍처, 개발 단계, 리스크를 정리하여 실제 구현 기준으로 활용하는 것을 목표로 합니다.

---

## 2. 프로젝트 개요

### 2.1 프로젝트명

**Remote AI Coder**

### 2.2 한 줄 설명

텔레그램 메시지만으로 집 또는 사무실 컴퓨터의 Claude Code/Codex/Gemini CLI를 실행해 코딩 작업을 자동 수행하고, 결과를 별도 Git 브랜치에 커밋한 뒤 사용자에게 알려주는 원격 AI 개발 자동화 시스템입니다.

### 2.3 추진 배경

외부 환경에서는 로컬 개발 머신, IDE, 터미널에 직접 접근하기 어렵습니다. 하지만 간단한 버그 수정, 리팩터링, 문서 수정, 테스트 보강 같은 작업은 자연어 지시만으로도 충분히 시작할 수 있습니다.

Remote AI Coder는 텔레그램을 원격 명령 인터페이스로 사용하여 사용자가 이동 중에도 로컬 개발 환경의 AI 코딩 도구를 안전하게 실행하고, 작업 결과를 Git 단위로 확인할 수 있도록 합니다.

### 2.4 핵심 목표

- 텔레그램 메시지를 통해 원격으로 AI 코딩 작업을 요청할 수 있습니다.
- 요청마다 격리된 Git 브랜치/작업 디렉토리에서 작업을 수행합니다.
- Claude Code 또는 Codex CLI 중 원하는 엔진을 선택해 실행할 수 있습니다.
- 작업 완료 후 수정 파일, 커밋, 브랜치, 오류 여부를 텔레그램으로 받을 수 있습니다.
- 로컬 개발 머신에 직접 접속하지 않아도 반복 가능한 코딩 자동화 워크플로우를 수행할 수 있습니다.

### 2.5 비목표

- 모바일에서 직접 코드를 편집하는 IDE를 만드는 것은 목표가 아닙니다.
- AI 작업 결과를 자동으로 운영 서버에 배포하는 것은 초기 범위에서 제외합니다.
- 여러 사용자가 동시에 사용하는 SaaS형 멀티테넌트 서비스는 초기 범위에서 제외합니다. (단, **단일 호스트에서 프로젝트마다 별도 Telegram 봇·allowlist**를 두는 로컬 멀티봇 구성은 지원합니다.)
- 완전 자동 승인 기반의 무제한 명령 실행 시스템을 지향하지 않습니다.

---

## 3. 대상 사용자 및 사용자 시나리오

### 3.1 대상 사용자

- 개인 개발자
- 로컬 머신에서 Claude Code/Codex/Gemini CLI를 사용하는 개발자
- 외부에서도 간단한 코드 수정, 문서 수정, 테스트 작성 등을 원격으로 요청하고 싶은 사용자

### 3.2 대표 사용자 시나리오

1. 사용자가 이동 중 텔레그램으로 다음 메시지를 보냅니다.
   > 현재 프로젝트의 로그인 유효성 검사 로직을 수정하고 `remote-auth` 브랜치에 커밋해줘.
2. 텔레그램 Bot Webhook이 FastAPI 서버로 메시지를 전달합니다.
3. 서버는 메시지를 검증하고 작업 요청으로 변환합니다.
4. 서버는 지정된 저장소에서 별도 worktree와 브랜치를 생성합니다.
5. 서버는 Claude Code, Codex CLI 또는 Gemini CLI를 비대화형 모드로 실행합니다.
6. AI 도구가 코드를 수정하고 필요한 검증 명령을 수행합니다.
7. 서버는 변경 사항을 확인한 뒤 커밋을 생성합니다.
8. 서버는 작업 결과를 텔레그램으로 전송합니다.
   > 작업 완료: `remote-auth` 브랜치에 2개 파일이 수정되었고 커밋이 생성되었습니다.

---

## 4. 제품 범위

### 4.1 MVP 범위

MVP에서는 **텔레그램 작업 요청 → 로컬 AI CLI 실행 → 별도 브랜치 커밋 → 텔레그램 결과 알림** 흐름을 완성합니다.

포함 기능:

- 텔레그램 Bot Webhook 수신
- 허용된 사용자만 명령 실행
- 기본 명령 파싱
- 기본 모델 선택: Claude, Codex 또는 Gemini
- Git worktree 기반 작업 격리
- AI CLI 비대화형 실행
- 작업 로그 저장
- 변경 파일 목록 수집
- 자동 커밋 생성
- 성공/실패 알림 전송

### 4.2 MVP 이후 확장 범위

- 작업 큐 및 동시 실행 제어
- 텔레그램 단일 채팅에서 여러 저장소를 오가는 UX(현재는 봇=프로젝트 바인딩으로 대체)
- 명령 템플릿 관리
- GitHub PR 생성 자동화
- 테스트 결과 요약
- 비용/토큰 사용량 추적
- 관리자 명령어 추가
- 작업 히스토리 조회
- 로컬 대시보드 UI

---

## 5. 기능 요구사항

### F1. 텔레그램 메시지 수신

- 시스템은 텔레그램 Bot API의 Webhook을 통해 메시지를 수신해야 합니다. URL은 `POST /telegram/webhook/{token_hash}` 형태이며, `token_hash`는 해당 봇 토큰 문자열의 SHA-256 16진 digest **앞 16자리**입니다(전체 digest 대신 짧은 라우팅 키 사용, 토큰 평문 노출 방지). 등록 시 동일 prefix 충돌은 거부합니다.
- 허용된 Telegram User ID 또는 Chat ID의 요청만 처리해야 합니다. Allowlist는 **등록된 프로젝트(봇)별**로 설정합니다.
- 허용되지 않은 사용자의 메시지는 실행하지 않고 거부해야 합니다.
- 텍스트 메시지 기반 명령을 우선 지원합니다.

### F2. 명령 파싱 및 작업 요청 생성

- 사용자의 자연어 메시지에서 다음 정보를 추출해야 합니다.
  - 대상 프로젝트 (Webhook으로 식별된 **봇 인스턴스에 고정**; 채팅에서 전환하지 않음)
  - 사용할 AI 모델
  - 작업 지시문
  - 브랜치명
  - 커밋 여부
- 명시되지 않은 값은 기본값을 사용할 수 있어야 합니다.
- 파싱이 불가능한 경우 사용자에게 재입력을 요청해야 합니다.
- 자연어 메시지는 파싱 후 즉시 실행하지 않고, 현재 프로젝트·작업 브랜치·사용 모델(및 모드)을 표시한 뒤 인라인 Yes/No 버튼으로 확인을 받아야 Job으로 생성합니다. 텍스트 `y`/`Y` 확인 경로는 제공하지 않습니다. `plan:`/`ask:`/`research:`/`계획:`/`질문:`/`조사:` 접두(ASCII 대소문자 무시, 콜론은 `:` 또는 `：`) 또는 `/plan`/`/ask`/`/research`로 시작하면 **읽기 전용** plan/ask/research 모드로 분류되며, 확인 절차는 agent와 동일하지만 실행 시 커밋·push는 하지 않고 detached worktree에서만 동작합니다. 본문 없이 `/plan`, `/ask`, 또는 `/research`만 입력하면 다음 메시지 1건을 해당 모드의 작업 지시문으로 받아 동일한 확인 절차를 진행해야 합니다. RESEARCH 모드는 저장소 맥락과 함께 선택된 AI CLI가 사용할 수 있는 인터넷 검색 기능으로 주어진 문제의 답을 찾도록 지시합니다. PLAN 모드는 계획 확정 전에 사용자 결정이 필요하면 모델이 구조화된 `plan-decisions` 블록(질문 최대 3개·옵션 2~4개)을 출력하고, 봇이 이를 인라인 버튼으로 한 번에 하나씩 물은 뒤 선택을 2차 PLAN 실행에 주입(detached worktree 재실행, 컨텍스트 주입)하여 최종 계획을 만듭니다. 결정이 없으면 1차 출력을 그대로 전달하며, 모든 모델에서 동일하게 동작합니다.
- 자연어 메시지가 이전 메시지에 답장(reply)인 경우, SQLite에 저장된 조상 메시지와 연결된 Job 결과 요약을 작업 지시문 앞에 포함할 수 있어야 합니다.
- reply로 연결된 Job들은 동일한 AI 세션으로 이어져야 합니다. 각 reply 체인은 루트 메시지를 기준으로 묶여 `session_id`가 부여되고(SQLite 저장·Job ID 연결), 러너는 네이티브 세션 재개(Claude `--session-id`/`--resume`, Codex `codex exec resume <id>`, Gemini `--resume <id>`)를 사용하며, provider가 재개를 지원하지 못하면 기존 reply 컨텍스트 주입으로 폴백합니다.

### F3. AI 모델 선택

- Claude Code, Codex CLI, Gemini CLI를 지원해야 합니다.
- `/model claude`, `/model codex`, `/model gemini` 명령으로 기본 모델을 변경할 수 있어야 합니다.
- 요청 메시지에 모델이 명시된 경우 해당 모델을 우선 사용해야 합니다.

### F4. Claude Code 실행

- Claude Code는 비대화형 실행을 기본으로 합니다.
- 예시 실행 방식:

  ```bash
  claude -p "작업 지시문" --dangerously-skip-permissions
  ```

- 작업 디렉토리는 해당 요청 전용 worktree여야 합니다.
- 실행 결과와 오류 로그를 저장해야 합니다.

### F5. Codex CLI 실행

- Codex CLI는 `exec` 기반 실행을 기본으로 합니다.
- 예시 실행 방식:

  ```bash
  codex exec "작업 지시문"
  ```

- 반복 가능한 워크플로우를 위해 프로젝트별 프롬프트/스크립트 확장이 가능해야 합니다.

### F5-1. Gemini CLI 실행

- Gemini CLI는 headless/non-interactive 실행을 기본으로 합니다.
- 예시 실행 방식:

  ```bash
  gemini --approval-mode yolo -p "작업 지시문"
  ```

- 작업 디렉토리는 해당 요청 전용 worktree여야 합니다.
- 실행 결과와 오류 로그를 저장해야 합니다.

### F6. Git 작업 자동화

- 요청마다 별도 worktree에서 작업하며, **변경이 있을 때만** 별도 브랜치를 생성합니다.
- 브랜치명 미지정 시 `remote/<timestamp>` 또는 `remote-<slug>-<timestamp>` 형식으로 자동 생성합니다.
- 기존 작업 디렉토리에 영향을 주지 않도록 Git worktree를 사용해야 합니다.
- AI 실행 후 변경 사항이 있으면 자동 커밋을 생성해야 합니다.
- 자동 커밋 메시지는 다음 형식을 따라야 합니다.

  ```text
  type: title
  - contents1
  - contents2

  committed by remote-coder: job-id
  ```

- 자동 커밋 메시지의 `title`은 기능 수정 내용을 한 줄로 요약해야 하며, 첫 번째 본문 항목은 사용자 원문이나 최근 수정 파일 목록이 아니라 AI Agent가 수행한 변경 내용을 설명해야 합니다.
- 변경 사항이 없으면 커밋하지 않고 “변경 없음”으로 보고해야 합니다.

### F7. 작업 상태 관리

- 작업은 다음 상태를 가져야 합니다.
  - `queued`
  - `running`
  - `succeeded`
  - `failed`
  - `cancelled`
- 각 작업은 고유한 Job ID를 가져야 합니다.
- 사용자는 Job ID를 통해 작업 결과를 확인할 수 있어야 합니다.

### F8. 결과 알림

- 작업 시작 시 접수 알림을 전송해야 합니다. 실행이 길어지면 접수 메시지를 약 1분 주기로 경과 시간(`⏳ 실행 중 (N분 경과)`)으로 갱신하고, 종료 시 원래 본문으로 복원합니다.
- 작업 완료 시 다음 정보를 전송해야 합니다.
  - 성공/실패 여부
  - 프로젝트명
  - 세션 ID(reply 체인이 같은 세션을 유지하는지 사용자가 확인할 수 있도록 Job ID와 함께 표시)
  - 브랜치명
  - 커밋 해시
  - 수정 파일 목록
  - 사용 모델(요청 모델 또는 CLI 출력에서 관측한 세부 모델)
  - 토큰 사용량(CLI 출력·로그에서 관측 가능한 경우)
  - 오류 요약
- 작업 결과 요약은 SQLite 대화 메모리에 저장하며, 사용 모델과 토큰 사용량이 있으면 함께 남겨야 합니다.
- 실패 시 에러 로그의 핵심 메시지를 요약해서 전송해야 합니다. 러너가 타임아웃·취소로 종료돼도 그때까지의 부분 출력을 로그에 저장하고 실패 알림에 요약으로 포함합니다.
- PLAN 성공 결과에는 **계획 실행** 인라인 버튼을 붙여, 한 번 누르면 승인된 계획(계획 본문·원요청을 컨텍스트로 주입)을 구현하는 AGENT 작업을 즉시 제출합니다.

### F9. 관리 명령어

초기 버전에서 다음 명령어를 지원합니다.

텔레그램 인라인 버튼은 반복 입력을 줄이기 위해 선택형 명령에 우선 적용합니다. `/model`, `/status`, `/branch`, `/rebase`, `/stop`, `/pr`, `/clear`, `/monitor`는 인자 없이 호출하면 선택 가능한 항목을 인라인 버튼으로 보여주고, 버튼 선택은 기존 슬래시 명령 실행 경로를 재사용합니다. `/help`와 `/help <topic>`은 설명 텍스트만 보여주며 기능 실행 버튼을 붙이지 않습니다. Webhook 등록 시 Telegram `setMyCommands`도 함께 호출해 클라이언트의 `/` 명령어 메뉴에 지원 명령어를 표시합니다(여기에는 `/plan`·`/ask`·`/research` 항목도 포함). 자연어 `plan:`/`ask:`/`research:` 접두에 대한 안내는 `/help`·`/help plan`·`/help ask`·`/help research` 및 `/start` 인라인 메뉴에 포함됩니다.

| 명령어 | 설명 |
|---|---|
| `/start` | 봇 사용 안내 |
| `/help` | 사용 가능한 명령어 확인 |
| `/model` | 현재 기본 모델 확인 및 인라인 모델 선택 |
| `/model claude` | 기본 모델을 Claude로 변경 |
| `/model codex` | 기본 모델을 Codex로 변경 |
| `/model gemini` | 기본 모델을 Gemini로 변경 |
| `/status` / `/status <job_id>` | 조회 가능한 Job 인라인 선택 / 작업 상태 조회 |
| `/init` | 이 채팅의 기본 모델 오버라이드·`/clear` 및 자연어 Job 확인 대기 상태 초기화(봇에 묶인 프로젝트 불변; SQLite·Git 미변경) |
| `/reports` | 현재 채팅·현재 프로젝트 기준으로 SQLite 대화 기억 요약 조회 |
| `/branch` / `/branch <이름>` | 이 채팅 적용 프로젝트의 현재 브랜치 조회 및 로컬 브랜치 인라인 선택 / 로컬 브랜치가 있으면 `git switch` |
| `/rebase` / `/rebase <branch>` | main/master를 제외하고 로컬과 원격에 모두 있는 브랜치 인라인 선택 / 적용 프로젝트에서 브랜치를 main 기준 rebase 후 main에 fast-forward 병합·push |
| `/stop` / `/stop <job_id>` | 진행 중인 Job 인라인 선택 / 작업 중단 요청 |
| `/pr` / `/pr <branch>` | 현재 프로젝트·채팅에서 성공한 Job 브랜치 중 설정 원격에 남아 있는 브랜치 인라인 선택 / 동일한 Job 소유권과 원격 존재 여부를 재검증한 뒤 `gh`로 main/master 대상 GitHub PR 생성 또는 기존 PR URL 조회 |
| `/clear branch` | 인라인 확인 버튼 승인 후 등록 프로젝트의 `remote-*` 로컬·원격 브랜치 및 연결 worktree 일괄 삭제 |
| `/clear memory` | 인라인 확인 버튼 승인 후 대화 기억 SQLite 데이터베이스 초기화 |
| `/monitor model` | 이 채팅 기본 모델 기준 CLI 인증/버전 조회, 로컬 CLI 로그에서 관측된 실제 세부 모델명·토큰 사용량 요약, Codex rate limit 스냅샷이 있는 경우 5시간/주간 잔여율·리셋 시각 표시 |
| `/monitor memory` | 현재 채팅·적용 프로젝트 기준 SQLite 대화 기억 행 수·역할별 행 수·DB 파일 크기 |
| `/monitor branch` | 적용 프로젝트 저장소의 현재 브랜치·로컬/원격 브랜치 수 및 목록 요약 |
| `/monitor worktrees` | `git worktree list` 기반 linked worktree·detached·managed 후보 요약 |
| `/monitor code` | 적용 프로젝트 루트 기준 코드 파일 수·줄 수 추정(확장자·제외 디렉터리 규칙 적용) |
| `/monitor project` | 이 봇에 바인딩된 프로젝트 레코드 요약 |
| 자연어 메시지 | 현재 프로젝트·작업 브랜치·사용 모델을 확인하고 인라인 Yes 버튼을 누르면 AI 작업 요청 생성 |

관리 UI의 웹 페이지 `/projects`에서 모든 등록 프로젝트·봇 메타데이터를 편집합니다. 텔레그램 `/project` 명령은 제공하지 않습니다.

공개 배포 기본 언어는 English입니다. 서버 전역 UI 언어는 로컬 전용 `/advanced` 화면에서 English/Korean 중 선택하며, Korean을 선택해도 기존 `계획:`·`질문:` 자연어 접두는 계속 호환합니다.

---

## 6. 비기능 요구사항

### N1. 보안

- 텔레그램 Webhook 엔드포인트는 HTTPS로 노출해야 합니다.
- 초기 개발 단계에서는 ngrok을 사용합니다.
- Telegram User ID/Chat ID allowlist를 반드시 적용합니다(프로젝트·봇별).
- Bot Token, API Key, 프로젝트 경로 등 민감 정보는 프로젝트 레지스트리 및 선택적 `.env` 시드로 관리합니다. 레지스트리 파일의 봇 토큰은 **평문**이므로 파일 권한·백업·커밋 제외를 엄격히 합니다. 장기적으로 OS 키링·암호화 저장을 검토합니다.
- AI CLI 실행 시 위험 명령 실행 가능성이 있으므로 허용 프로젝트 경로를 제한합니다.
- 임의 shell 명령을 직접 입력받아 실행하지 않습니다.

### N2. 안정성

- AI 작업은 FastAPI 요청 처리와 분리된 백그라운드 작업으로 실행합니다.
- 장시간 작업으로 인해 Webhook 응답이 지연되지 않아야 합니다.
- 작업별 timeout을 설정해야 합니다.
- 프로세스 실패, Git 실패, CLI 실패를 구분해서 기록해야 합니다.

### N3. 확장성

- AI 엔진은 인터페이스 형태로 추상화하여 Claude/Codex/Gemini 외 도구를 추가할 수 있어야 합니다.
- 프로젝트 설정은 코드에 하드코딩하지 않고 설정 파일로 분리합니다.
- 작업 큐는 초기에는 인메모리로 시작하되, 이후 SQLite/Redis로 확장 가능해야 합니다.

### N4. 사용성

- 사용자는 가능한 한 자연어로 요청할 수 있어야 합니다.
- 시스템은 중요한 기본값을 자동 적용해야 합니다.
- 실패 메시지는 사용자가 다음 행동을 결정할 수 있을 정도로 구체적이어야 합니다.

### N5. 설치 및 배포

- 서버는 Python 패키지로 빌드할 수 있어야 하며, 공개 전 초기 버전은 `v0.0.1`로 관리합니다.
- 설치된 사용자는 `remote-coder` CLI로 서버를 실행할 수 있어야 합니다.
- Homebrew 배포는 macOS 앱 번들용 Cask보다 CLI Formula 방식을 우선 검토합니다.

---

## 7. 시스템 아키텍처

### 7.1 구성 요소

```text
Telegram User
    │
    ▼
Telegram Bot API
    │ Webhook
    ▼
ngrok HTTPS Tunnel
    │
    ▼
FastAPI Server
    ├─ Auth & Command Parser
    ├─ Job Manager
    ├─ Git Worktree Manager
    ├─ AI Runner Interface
    │   ├─ Claude Runner
    │   ├─ Codex Runner
    │   └─ Gemini Runner
    ├─ Log/State Storage
    └─ Telegram Notifier
        │
        ▼
Telegram Bot API
```

### 7.2 주요 모듈

| 모듈 | 역할 |
|---|---|
| Webhook Controller | 텔레그램 Webhook 수신·16자리 `token_hash` prefix 정확 일치 라우팅 및 기본 검증 |
| Auth Service | 허용 사용자 확인(봇·프로젝트별 인스턴스) |
| Bot Instance Manager | 봇별 notifier·auth·컨텍스트 등록 및 조회 |
| Command Parser | 자연어/명령어를 작업 요청으로 변환 |
| Job Manager | 작업 생성, 상태 변경, 백그라운드 실행 관리; Job 알림은 `JobRequest.project`로 선택한 봇별 Notifier로 발송 |
| Git Service | worktree 생성, 브랜치 생성, diff 확인, 커밋 |
| AI Runner | Claude/Codex/Gemini 실행 추상화 |
| Notifier | 텔레그램 메시지 전송 |
| Storage | 작업 상태, 로그, 설정 저장 |

---

## 8. 기술 스택

| 영역 | 기술 |
|---|---|
| 언어 | Python 3.11+ |
| API 서버 | FastAPI |
| 비동기 서버 | Uvicorn |
| 메시징 | Telegram Bot API |
| 외부 HTTPS 터널 | ngrok |
| AI CLI | Claude Code, Codex CLI, Gemini CLI |
| 버전 관리 | Git, Git worktree |
| 설정 관리 | `.env`, YAML/JSON config |
| 패키징 | `pyproject.toml`, console script, Homebrew Formula 템플릿 |
| 초기 저장소 | 파일 기반 JSON 또는 SQLite |
| 테스트 | pytest |

---

## 9. 데이터 및 설정 구조

### 9.1 환경 변수 예시

```env
# 선택 시드(레지스트리가 비어 있을 때 첫 프로젝트 생성 보조). 운영은 projects.json 등을 우선.
TELEGRAM_BOT_TOKEN=xxxxxxxx
TELEGRAM_ALLOWED_CHAT_IDS=123456789
TELEGRAM_WEBHOOK_SECRET=change-me-to-a-long-random-secret
DEFAULT_MODEL=claude
JOB_TIMEOUT_SECONDS=1800
# 워크트리와 상태 파일은 ~/.remote-coder 아래에서 자동 관리됩니다(워크트리 경로 설정 불필요).
# JOB_DB_PATH 미설정 시 ~/.remote-coder/jobs.sqlite3 사용
```

### 9.2 프로젝트 설정 예시

레지스트리(JSON)에서는 프로젝트마다 `bot_token`, `allowed_chat_ids`, 선택적 `webhook_secret`, `allowed_user_ids`, Git 경로 등을 둡니다. 관리 UI 또는 문서 `docs/multi-bot-setup.md` 참고.

레거시 YAML 예시(개념용):

```yaml
projects:
  remote-coder:
    path: /Users/example/Git/remote-coder
    default_branch: main
    test_command: pytest
    allowed_models:
      - claude
      - codex
```

### 9.3 Job 데이터 예시

```json
{
  "id": "job_20260427_155201",
  "project": "remote-coder",
  "model": "claude",
  "status": "succeeded",
  "branch": "remote-auth",
  "commit": "abc1234",
  "runner_actual_model": "Claude Sonnet 4.5",
  "runner_token_usage": {
    "input": 1200,
    "output": 300
  },
  "created_at": "2026-04-27T15:52:01+09:00",
  "finished_at": "2026-04-27T15:58:20+09:00"
}
```

---

## 10. 기본 동작 흐름

### 10.1 작업 요청 처리 흐름

1. Webhook 수신 (URL의 16자리 `token_hash` prefix로 봇·프로젝트 인스턴스 선택)
2. 사용자 인증
3. 명령어/자연어 파싱
4. Job 생성
5. 접수 메시지 전송
6. Git worktree 생성
7. AI CLI 실행
8. 변경 사항 확인
9. 커밋 생성
10. worktree 정리 여부 결정
11. 결과 메시지 전송

### 10.2 실패 처리 흐름

1. 실패 지점 기록
2. 로그 저장
3. Job 상태를 `failed`로 변경
4. 사용자에게 실패 원인 요약 전송
5. worktree 보존 또는 정리 정책 적용

---

## 11. 개발 로드맵

### Phase 1. 프로젝트 골격 구축

- FastAPI 프로젝트 생성
- 환경 변수 로딩
- Telegram Webhook 엔드포인트 구현
- `/start`, `/help` 명령어 구현

### Phase 2. 작업 실행 MVP

- 사용자 allowlist 적용
- 명령 파서 1차 구현
- Job Manager 구현
- Claude Runner 구현
- Git worktree 생성/커밋 구현
- 완료/실패 알림 구현

### Phase 3. Codex 및 설정 확장

- Codex Runner 구현
- Gemini Runner 구현
- `/model` 명령 구현
- 프로젝트 설정 파일 도입
- 관리 UI 프로젝트 CRUD 및 멀티봇 webhook; `/status` 구현

### Phase 4. 안정화

- timeout 처리
- 로그 저장 구조 개선
- 테스트 코드 작성
- 에러 메시지 정리
- worktree 정리 정책 적용
- Python 패키지 메타데이터와 CLI 진입점 정리

### Phase 5. 고도화

- 프로젝트별 인메모리 실행 잠금 적용(완료), 재시작 복구가 가능한 내구성 작업 큐 검토
- SQLite 기반 Job 저장
- PR 생성 자동화
- 테스트 결과 요약
- 로컬 대시보드 검토
- Homebrew Formula 배포 자동화 검토

### 중기 계획. 운영 안정성과 작업 흐름 고도화

중기 목표는 "텔레그램으로 요청하면 믿고 맡길 수 있는 개인 운영 도구" 수준까지 안정화하는 것입니다. 핵심은 실패 복구, 작업 추적, 리뷰 흐름, 모바일 확인 경험입니다.

1. 내구성 작업 큐와 재시작 복구
   - 서버 재시작 후에도 `queued`/`running` Job 상태를 SQLite에서 복원합니다.
   - 실행 중 서버가 종료된 Job은 `failed` 또는 `cancelled`로 정리하고, 보존된 로그와 worktree 위치를 알립니다.
   - 프로젝트별 동시 실행 잠금은 유지하되, 큐 대기 순서와 취소 정책을 명확히 합니다.

2. 작업 결과 리뷰 UX 개선
   - 완료 알림에 변경 파일, 커밋, 테스트 결과, 주요 diff 요약을 함께 표시합니다.
   - 모바일에서 긴 diff를 읽기 어렵기 때문에 파일별 핵심 변경 요약과 위험 파일 표시를 우선 제공합니다.
   - "계획 실행" 이후에도 결과를 다시 검토하고 후속 수정 Job으로 자연스럽게 이어갈 수 있게 reply 세션 연결을 강화합니다.

3. GitHub PR 자동화
   - `/pr` 명령을 안정화해 성공한 Job 브랜치에서 PR을 만들거나 기존 PR URL을 반환합니다.
   - PR 본문에는 원 요청, 모델, 테스트 결과, 변경 요약, known limitations를 자동 포함합니다.
   - PR 생성 전 원격 브랜치 존재 여부와 Job 소유권을 재검증합니다.

4. 관측성과 운영 진단
   - `/monitor` 계열 명령을 정리해 모델 인증, rate limit, 메모리 DB, worktree, 브랜치 상태를 한 화면에서 점검할 수 있게 합니다.
   - Job, Git, Runner, Telegram 경계에서 구조화 로그를 일관되게 남깁니다.
   - 실패 유형별 메시지를 정리해 사용자가 재시도, 설정 수정, 수동 확인 중 무엇을 해야 할지 알 수 있게 합니다.

5. 설치와 업데이트 흐름 정리
   - `remote-coder` CLI 실행, 초기 프로젝트 등록, webhook 등록, ngrok 연결 절차를 문서와 명령으로 단순화합니다.
   - Homebrew Formula 배포를 검토하고, 로컬 개발 설치와 사용자 설치 경로를 분리합니다.
   - 설정 파일과 레지스트리 마이그레이션 정책을 마련합니다.

### 장기 계획. 개인용 자동 개발 에이전트 플랫폼화

장기 목표는 단일 원격 실행 도구를 넘어, 여러 로컬 프로젝트의 작업 요청·계획·리뷰·릴리스를 일관되게 관리하는 개인용 자동 개발 플랫폼으로 확장하는 것입니다.

1. 로컬 대시보드
   - 프로젝트 목록, 최근 Job, 브랜치, PR, 로그, 모델 사용량을 웹 UI에서 조회합니다.
   - Telegram에서 시작한 작업도 대시보드에서 이어서 확인할 수 있게 Job 상세 화면을 제공합니다.
   - 민감 설정은 로컬 전용 관리 화면에서만 수정하며, 외부 공개를 전제로 하지 않습니다.

2. 안전한 권한 모델
   - 봇 토큰과 프로젝트 레지스트리를 OS 키링 또는 암호화 저장소로 옮기는 방안을 검토합니다.
   - 프로젝트별 허용 경로, 허용 모델, timeout, push/PR 권한을 세분화합니다.
   - 위험 작업은 추가 확인 버튼이나 읽기 전용 plan 모드를 거치도록 정책화합니다.

3. 에이전트 품질 관리
   - 모델별 실행 옵션, 프롬프트 템플릿, 검증 명령을 프로젝트별로 조정할 수 있게 합니다.
   - 실패한 Job과 성공한 Job의 패턴을 SQLite에 축적해 재시도 프롬프트와 요약 품질을 개선합니다.
   - 테스트 결과, lint 결과, diff 위험도를 바탕으로 자동 커밋 여부를 더 보수적으로 판단합니다.

4. 다중 프로젝트 운영 경험
   - 봇 인스턴스가 프로젝트 컨텍스트라는 원칙은 유지하되, 관리 UI에서 프로젝트 등록·비활성화·webhook 재등록을 쉽게 처리합니다.
   - 프로젝트별 기본 모델, 기본 브랜치, 테스트 명령, PR 대상 브랜치를 UI에서 관리합니다.
   - 장기적으로 개인 서버 한 대에서 여러 저장소를 안정적으로 운영할 수 있는 백업과 복원 절차를 제공합니다.

5. 릴리스와 배포 보조
   - 자동 배포는 기본 목표가 아니지만, 릴리스 노트 작성, 버전 bump, 태그 준비 같은 보조 작업을 안전하게 지원합니다.
   - `RELEASE.md` 기반 체크리스트 실행을 Telegram 또는 대시보드에서 추적할 수 있게 합니다.
   - 실제 `git push`, tag, 배포 명령은 명시적 사용자 확인이 있을 때만 수행합니다.

---

## 12. 주요 리스크 및 대응 방안

| 리스크 | 설명 | 대응 방안 |
|---|---|---|
| 원격 명령 실행 위험 | AI가 위험한 명령을 실행할 수 있음 | 허용 프로젝트 경로 제한, 사용자 allowlist, 로그 기록 |
| 비정상 커밋 생성 | AI가 의도와 다른 코드를 수정할 수 있음 | 별도 브랜치/worktree 사용, 자동 배포 금지 |
| 장시간 작업 | Webhook 요청이 timeout될 수 있음 | 백그라운드 작업 분리, 즉시 접수 응답 |
| 토큰/API 한도 | AI CLI가 중간 실패할 수 있음 | 실패 요약 알림, 재시도 가능 구조 |
| ngrok URL 변경 | 재시작 시 Webhook URL이 바뀔 수 있음 | 시작 스크립트에서 Webhook 자동 등록 |
| 동시 작업 충돌 | 같은 프로젝트에 여러 요청이 들어올 수 있음 | 프로젝트별 인메모리 실행 잠금 적용, 내구성 작업 큐 검토 |

---

## 13. 완료 기준

MVP는 다음 조건을 만족하면 완료된 것으로 봅니다.

- 텔레그램에서 허용된 사용자의 메시지를 수신할 수 있습니다.
- 자연어 작업 요청을 Job으로 생성할 수 있습니다.
- Git worktree와 브랜치를 자동 생성할 수 있습니다.
- Claude Code를 비대화형으로 실행할 수 있습니다.
- 변경 사항을 자동 커밋할 수 있습니다.
- 성공/실패 결과를 텔레그램으로 받을 수 있습니다.
- 기본 사용법이 README 또는 문서에 정리되어 있습니다.

---

## 14. 향후 검토 사항

- 봇 토큰 저장: 평문 파일 대신 OS 키링·암호화 at-rest 등 대안
- Claude Hook 기반 완료 감지와 서버 프로세스 기반 완료 감지 중 어떤 방식을 우선할지 결정
- Codex CLI 실행 옵션 및 승인 모드 세부 확인
- worktree를 작업 후 자동 삭제할지, 디버깅을 위해 보존할지 정책 결정
- PR 자동 생성 기능 도입 여부 결정
- 모바일 환경에서 결과 diff를 어떻게 요약해 보여줄지 결정
