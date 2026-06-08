# Claude 사용자 가이드

Remote AI Coder를 Claude CLI로 사용하는 사람을 위한 문서입니다.

## 1) 전제 조건

- macOS 또는 Linux 셸 사용 가능
- `conda activate remote-coder` 가능한 환경
- Telegram Bot/Webhook 기본 설정 완료

## 2) Claude CLI 설치 확인

```bash
command -v claude
```

- 경로가 출력되면 설치됨
- 아무것도 출력되지 않으면 Claude CLI 설치가 필요함

## 3) Claude 로그인

Remote AI Coder 서버를 실행하는 **같은 OS 사용자 계정**에서 로그인해야 합니다.

```bash
claude
```

- CLI 안내에 따라 `/login`을 완료합니다.
- 과거 실패 로그에 `Not logged in · Please run /login`가 보이면 로그인 누락입니다.

## 4) 단독 스모크 테스트 (권장)

서버 연동 전에 Claude 단독 실행이 되는지 확인합니다.

```bash
cd /tmp
claude -p "Say hello in one line" --dangerously-skip-permissions
```

- 한 줄 응답이 나오면 CLI 실행 준비 완료

## 5) Remote AI Coder에서 Claude 사용

1. 서버 실행

```bash
remote-coder up
```

2. Telegram에서 모델 지정

```text
/model claude
```

3. 작은 자연어 작업 테스트

```text
README에 테스트 문구 한 줄 추가해줘 no commit
```

## 6) 모델 선택 우선순위 (현재 코드 기준)

자연어 요청에서 모델은 아래 순서로 선택됩니다.

1. 메시지의 `model: ...` 옵션
2. chat별 `/model` 설정값
3. 그 외 기본값 (현재 구현에서는 `DEFAULT_MODEL` 영향이 큼)

예시:

```text
model: claude branch: test-branch README 정리해줘
```

## 7) 자주 발생하는 문제

### `Not logged in · Please run /login`

- 원인: Claude 계정 로그인 안 됨
- 조치: 서버 실행 계정에서 `claude` 실행 후 로그인

### Telegram에는 접수되는데 결과가 실패로 옴

- 작업 로그 확인: `~/.remote-coder/worktrees/<project>/_logs/<job_id>.log`
- 실패 단계(`runner`, `git_commit` 등)를 먼저 확인
- Telegram 메시지에는 요약본만 표시되며, 상세 원문(stdout/stderr)은 로그 파일에서 확인

### worktree 읽기 전용·수정 불가 메시지

- 서버는 worktree 경로에 임시 파일을 써서 쓰기 가능 여부를 먼저 확인합니다. 실패 시 `git_worktree` 단계에서 끝납니다.
- 종료 코드가 0이어도 출력에 `read-only` / `readonly` / `읽기 전용` / `수정 불가`가 있고 Git 변경이 없으면 **실패**로 처리됩니다. 워크트리 베이스(`~/.remote-coder/worktrees/`) 권한과 마운트 옵션을 확인하세요.
- 단계별 점검은 [read-only 워크스페이스 가이드](read-only-workspace.md)를 참고하세요.

### 권한 옵션 관련 주의

현재 Runner는 아래 커맨드로 실행됩니다.

```text
claude -p "<instruction>" --dangerously-skip-permissions
```

- 반드시 허용된 프로젝트 경로/allowlist 환경에서만 사용하세요.
- 신뢰되지 않은 요청을 그대로 실행하지 않도록 운영 정책을 유지하세요.
