# Gemini 사용자 가이드

Remote AI Coder를 Gemini CLI로 사용하는 사람을 위한 문서입니다.

## 1) 전제 조건

- macOS 또는 Linux 셸 사용 가능
- `conda activate remote-coder` 가능한 환경
- Telegram Bot/Webhook 기본 설정 완료
- Node.js/npm 사용 가능

## 2) Gemini CLI 설치 확인

```bash
command -v gemini
```

- 경로가 출력되면 설치됨
- 아무것도 출력되지 않으면 Gemini CLI 설치가 필요함

Gemini CLI가 아직 없다면 다음처럼 설치할 수 있습니다.

```bash
npm install -g @google/gemini-cli
```

설치 후 새 터미널을 열거나 PATH를 다시 로드한 뒤 `command -v gemini`를 재확인하세요.

## 3) Gemini 인증

Remote AI Coder 서버를 실행하는 **같은 OS 사용자 계정**에서 인증해야 합니다.

```bash
gemini
```

- 대화형 화면에서 `/auth`를 실행하거나 CLI 안내에 따라 인증을 완료합니다.
- 인증이 안 된 상태에서 Remote AI Coder를 쓰면 `runner` 단계 실패가 발생할 수 있습니다.
- 인증 상태나 계정/쿼터 관련 상세 내용은 Gemini CLI 또는 Google 계정/프로젝트 설정에서 확인하세요.

## 4) 단독 스모크 테스트 (권장)

서버 연동 전에 Gemini 단독 실행이 되는지 확인합니다.

```bash
cd /tmp
gemini --approval-mode yolo -p "Say hello in one line"
```

- 한 줄 응답이 나오면 CLI 실행 준비 완료
- `gemini` 명령을 찾을 수 없으면 설치 또는 PATH 설정을 먼저 점검
- 인증/쿼터 오류가 나오면 대화형 `gemini` 실행 후 인증 상태를 재확인

## 5) Remote AI Coder에서 Gemini 사용

1. 서버 실행

```bash
remote-coder up
```

2. Telegram에서 모델 지정

```text
/model gemini
```

3. 작은 자연어 작업 테스트

```text
model: gemini README에 테스트 문구 한 줄 추가해줘 no commit
```

## 6) 모델 선택 우선순위 (현재 코드 기준)

자연어 요청에서 모델은 아래 순서로 선택됩니다.

1. 메시지의 `model: ...` 옵션
2. chat별 `/model` 설정값
3. 그 외 기본값 (현재 구현에서는 `DEFAULT_MODEL` 영향이 큼)

예시:

```text
model: gemini branch: gemini-doc-test README 정리해줘
```

프로젝트 기본 모델(`projects.json`)이 `gemini`여도, chat 설정이 `claude`면 chat 설정이 우선될 수 있습니다. 특정 요청에서 Gemini를 강제하려면 메시지에 `model: gemini`을 명시하세요.

## 7) 실행 방식과 권한 옵션 관련 주의

현재 Gemini Runner는 아래 커맨드로 실행됩니다.

```text
gemini --approval-mode yolo -p "<instruction>"
```

- `--approval-mode yolo`는 Gemini CLI가 작업 중 필요한 변경을 비대화형으로 진행하도록 허용하는 위험 옵션입니다.
- 반드시 허용된 프로젝트 경로, Telegram allowlist, Job worktree 격리가 적용된 환경에서만 사용하세요.
- 신뢰되지 않은 요청을 그대로 실행하지 않도록 운영 정책을 유지하세요.

## 8) 자주 발생하는 문제

### `gemini` 명령을 찾을 수 없음

- 원인: Gemini CLI 미설치 또는 PATH 미설정
- 조치: `npm install -g @google/gemini-cli` 설치 후 `command -v gemini` 재확인

### Telegram 작업이 runner 단계에서 실패

- 작업 로그 확인: `<WORKTREE_BASE_DIR>/_logs/<job_id>.log`
- CLI 단독 테스트(`gemini --approval-mode yolo -p ...`)가 먼저 성공하는지 점검
- 인증/쿼터/모델 접근 권한 문제는 Gemini CLI의 오류 메시지를 기준으로 확인
- Telegram 메시지에는 요약본만 표시되며, 상세 원문(stdout/stderr)은 로그 파일에서 확인

### worktree 읽기 전용·수정 불가 메시지

- 서버는 worktree 경로에 임시 파일을 써서 쓰기 가능 여부를 먼저 확인합니다. 실패 시 `git_worktree` 단계에서 끝납니다.
- 종료 코드가 0이어도 출력에 `read-only` / `readonly` / `읽기 전용` / `수정 불가`가 있고 Git 변경이 없으면 **실패**로 처리됩니다. `WORKTREE_BASE_DIR` 권한과 마운트 옵션을 확인하세요.
- 단계별 점검은 [read-only 워크스페이스 가이드](read-only-workspace.md)를 참고하세요.

### 프로젝트 기본값과 실제 동작 모델이 다름

- `/model` 명령으로 chat별 설정을 확인/변경
- 필요하면 요청마다 `model: gemini`를 명시해 강제
