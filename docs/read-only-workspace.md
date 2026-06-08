# Worktree read-only(읽기 전용) 문제 해결 가이드

Remote AI Coder는 AI 작업을 **Git detached worktree** 안에서 실행합니다. 여기서 “read-only”가 나오는 원인은 **실제 디스크에 쓸 수 없는 경우**와 **Claude/Codex CLI가 수정을 거부하거나 그렇게 표현하는 경우**로 나눌 수 있습니다. 아래 순서로 점검하면 원인을 좁히기 쉽습니다.

## 1. 앱이 하는 검사를 이해하기

1. **Worktree 쓰기 점검**  
   Job worktree 경로(`~/.remote-coder/worktrees/<project>/<job_id>`)에 임시 파일을 만들었다가 지워 **OS 수준에서 쓰기 가능한지** 확인합니다. 여기서 실패하면 Job은 `git_worktree` 단계에서 실패합니다.

2. **Runner 출력과 Git 변경의 조합**  
   Claude 또는 Codex가 **종료 코드 0**으로 끝났더라도, 표준 출력·표준 오류에 `read-only`, `readonly`, `읽기 전용`, `수정 불가` 같은 표현이 있고 **Git 변경 파일이 하나도 없으면** “실제로는 작업이 되지 않았다”고 보고 Job을 **실패**로 처리합니다.

따라서 Telegram 알림의 **실패 단계**와 **`~/.remote-coder/worktrees/<project>/_logs/<job_id>.log`** 원문을 함께 보는 것이 첫 단계입니다.

## 2. OS·파일 시스템 쪽에서 풀 수 있는 경우

### 2.1 디렉터리 권한·소유자

- 서버(예: `uvicorn`으로 FastAPI를 띄운 **OS 사용자**)가 워크트리 베이스(`~/.remote-coder/worktrees/`)와 그 아래에 **디렉터리 생성·파일 쓰기**를 할 수 있어야 합니다.
- 확인 예: 해당 사용자로 터미널에 접속한 뒤, `~/.remote-coder/worktrees/` 아래에 임시 파일을 만들어 볼 수 있는지 확인합니다.
- 필요하면 `REMOTE_CODER_HOME`을 **그 사용자 소유이고 쓰기 가능한 경로**로 옮겨 워크트리 베이스를 함께 이동시킵니다. 불필요하게 `777`을 쓰기보다는 소유자(`chown`)를 맞추는 편이 안전합니다.

### 2.2 읽기 전용 마운트

- 외장 디스크, 네트워크 볼륨, 보안/동기화 도구가 붙인 **read-only 마운트** 아래에 worktree를 두면 앱이 쓰기 검사에서 실패하거나, 이후 단계에서 계속 문제가 납니다.
- 이 경우 `REMOTE_CODER_HOME`을 **로컬 일반 디스크의 쓰기 가능한 디렉터리**로 옮겨 워크트리 베이스를 함께 이동시키는 것이 근본 해결입니다.

### 2.3 다른 프로세스와의 충돌

- 백업·클라우드 동기화가 해당 트리를 잠그는 경우가 있습니다. 가능하면 worktree 베이스 경로를 제외 목록에 넣거나, 동기화 대상 밖으로 빼냅니다.

## 3. AI CLI 쪽 (Claude / Codex)

- 디스크 권한은 정상인데도 CLI가 “read-only”라고만 말하는 경우가 있습니다. **서버를 실행하는 것과 동일한 사용자·같은 머신**에서 단독 스모크 테스트를 합니다.
- 절차는 모델별 가이드를 따릅니다.
  - [Claude 가이드](claude-guide.md) — CLI 설치, 로그인, `claude -p ...` 단독 테스트
  - [Codex 가이드](codex-guide.md) — `codex exec ...` 단독 테스트, **`--sandbox workspace-write`** 등 샌드박스 옵션
- **Codex만 해당**: 터미널에 `sandbox: read-only`가 나오면 Codex CLI의 샌드박스 모드일 수 있습니다. Remote AI Coder는 기본으로 `workspace-write`를 넘기지만, 관리 UI 고급 설정의 `codex_sandbox`가 `read-only`인지 확인하세요.
- 로그인 누락, PATH, CLI 버전·정책 차이를 의심합니다. 가이드의 “자주 발생하는 문제” 절도 함께 참고하세요.

## 4. 설정으로 바꿀 수 있는 것

- **Worktree 베이스**: `~/.remote-coder/worktrees/<project>/`가 실제로 쓰이는 루트입니다. 위치를 바꾸려면 `REMOTE_CODER_HOME`을 쓰기 가능한 경로로 옮깁니다.
- **대화 SQLite(`CONVERSATION_DB_PATH`)**는 “맥락 저장”용이며, worktree의 read-only와는 별개입니다.

## 5. 요약 체크리스트

1. Job 실패 메시지의 **실패 단계** 확인 (`git_worktree` vs `runner` 등).
2. **`~/.remote-coder/worktrees/<project>/_logs/<job_id>.log`**에서 stdout/stderr 전문 확인.
3. 서버 OS 사용자 기준으로 **`~/.remote-coder/worktrees/` 쓰기** 가능 여부 확인.
4. **마운트 옵션·동기화 도구** 여부 확인.
5. **Claude/Codex 단독 실행**으로 동일 환경에서 수정 가능한지 확인.

위를 모두 통과했는데도 동일 증상이면, CLI 쪽 릴리스 노트·지원 채널을 확인하는 것이 다음 단계입니다.
