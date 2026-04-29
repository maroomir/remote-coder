# Codex 사용자 가이드

Remote AI Coder를 Codex CLI로 사용하는 사람을 위한 문서입니다.

## 1) 전제 조건

- macOS 또는 Linux 셸 사용 가능
- `conda activate remote-coder` 가능한 환경
- Telegram Bot/Webhook 기본 설정 완료

## 2) Codex CLI 설치 확인

```bash
command -v codex
```

- 경로가 출력되면 설치됨
- 아무것도 출력되지 않으면 Codex CLI 설치가 필요함

## 3) Codex 로그인

Remote AI Coder 서버를 실행하는 **같은 OS 사용자 계정**에서 로그인해야 합니다.

```bash
codex --help
```

- 로그인 절차가 필요한 경우 CLI 안내에 따라 먼저 인증을 완료합니다.
- 인증이 안 된 상태에서 Remote AI Coder를 쓰면 `runner` 단계 실패가 발생할 수 있습니다.

## 4) 단독 스모크 테스트 (권장)

서버 연동 전에 Codex 단독 실행이 되는지 확인합니다.

```bash
cd /tmp
codex exec "print a one line greeting"
```

- 정상 출력이 나오면 CLI 실행 준비 완료
- 터미널 헤더에 `sandbox: read-only`만 보이면 **Codex 기본 비대화형 정책**일 수 있습니다. 실제로 파일을 수정하는 스모크는 예를 들어 아래처럼 `workspace-write`를 명시합니다.

```bash
cd /path/to/your/git/repo
codex exec --sandbox workspace-write "README에 테스트용 한 줄만 추가하고 설명해줘"
```

## 4.5) 샌드박스와 Remote AI Coder

- OpenAI Codex CLI의 `codex exec`는 기본이 **read-only 샌드박스**에 가깝게 동작해, 편집이 막힐 수 있습니다.
- Remote AI Coder는 기본으로 **`--sandbox workspace-write`**를 붙여 Job worktree(`cwd`) 안에서 파일 수정이 되도록 합니다.
- 환경 변수 **`CODEX_SANDBOX`**로 바꿀 수 있습니다. 값은 `read-only`, `workspace-write`, `danger-full-access` 중 하나입니다. `danger-full-access`는 샌드박스를 사실상 해제하므로 신뢰된 환경에서만 사용하세요.

## 5) Remote AI Coder에서 Codex 사용

1. 서버 실행

```bash
./run.sh
```

2. Telegram에서 모델 지정

```text
/model codex
```

3. 작은 자연어 작업 테스트

```text
model: codex README에 테스트 문구 한 줄 추가해줘 no commit
```

## 6) 모델 선택 우선순위 (현재 코드 기준)

자연어 요청에서 모델은 아래 순서로 선택됩니다.

1. 메시지의 `model: ...` 옵션
2. chat별 `/model` 설정값
3. 그 외 기본값 (현재 구현에서는 `DEFAULT_MODEL` 영향이 큼)

프로젝트 기본 모델(`projects.json`)이 `codex`여도, chat 설정이 `claude`면 chat 설정이 우선될 수 있습니다.

## 7) 자주 발생하는 문제

### `codex` 명령을 찾을 수 없음

- 원인: Codex CLI 미설치 또는 PATH 미설정
- 조치: Codex CLI 설치 후 `command -v codex` 재확인

### Telegram 작업이 runner 단계에서 실패

- 작업 로그 확인: `<WORKTREE_BASE_DIR>/_logs/<job_id>.log`
- CLI 단독 테스트(`codex exec ...`)가 먼저 성공하는지 점검
- Telegram 메시지에는 요약본만 표시되며, 상세 원문(stdout/stderr)은 로그 파일에서 확인

### worktree 읽기 전용·수정 불가 메시지

- 서버는 worktree 경로에 임시 파일을 써서 쓰기 가능 여부를 먼저 확인합니다. 실패 시 `git_worktree` 단계에서 끝납니다.
- 종료 코드가 0이어도 출력에 `read-only` / `readonly` / `읽기 전용` / `수정 불가`가 있고 Git 변경이 없으면 **실패**로 처리됩니다. `WORKTREE_BASE_DIR` 권한과 마운트 옵션을 확인하세요.
- 단계별 점검은 [read-only 워크스페이스 가이드](read-only-workspace.md)를 참고하세요.

### 프로젝트 기본값과 실제 동작 모델이 다름

- `/model` 명령으로 chat별 설정을 확인/변경
- 필요하면 요청마다 `model: codex`를 명시해 강제
