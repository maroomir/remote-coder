# AI 러너 가이드

*English: [ai-runners.md](ai-runners.md) · 한국어: 이 문서*

Remote AI Coder는 Claude Code, Codex CLI, Gemini CLI, Ollama를 같은 Job 흐름에서 실행합니다. 어떤 모델을 쓰든 서버를 실행하는 **같은 OS 사용자 계정**에서 도구 설치, 필요한 인증, PATH 설정이 완료되어 있어야 합니다.

## 공통 체크

1. `remote-coder doctor`로 설치 상태를 확인합니다.
2. 사용할 CLI를 단독으로 한 번 실행해 인증과 권한을 확인합니다.
3. Telegram에서 `/model`로 기본 모델을 선택하거나, 요청마다 `model: claude`, `model: codex`, `model: gemini`, `model: ollama`를 명시합니다.
4. 실패하면 Telegram 요약만 보지 말고 `~/.remote-coder/worktrees/<project>/_logs/<job_id>.log` 원문을 확인합니다.

모델 선택 우선순위:

1. 자연어 요청의 `model: ...` 옵션
2. 현재 채팅의 `/model` 설정
3. 프로젝트 레지스트리의 `default_model`

## Claude Code

설치 확인:

```bash
command -v claude
```

로그인과 단독 실행:

```bash
claude
cd /tmp
claude -p "Say hello in one line" --dangerously-skip-permissions
```

Remote AI Coder에서 사용:

```text
/model claude
README 문구를 더 간결하게 정리해줘
```

주의할 점:

- `Not logged in · Please run /login`이 나오면 서버 실행 계정에서 `claude`를 열고 로그인하세요.
- Claude 러너는 비대화형 실행을 위해 `--dangerously-skip-permissions`를 사용합니다. Telegram allowlist와 프로젝트 경로 제한을 반드시 유지하세요.

## Codex CLI

설치 확인:

```bash
command -v codex
```

단독 실행:

```bash
cd /tmp
codex exec "print a one line greeting"
```

파일 수정까지 확인하려면 테스트 저장소에서 쓰기 가능한 샌드박스를 명시합니다.

```bash
cd /path/to/your/git/repo
codex exec --sandbox workspace-write "README에 테스트용 한 줄만 추가하고 설명해줘"
```

Remote AI Coder에서 사용:

```text
/model codex
model: codex README 문구를 더 간결하게 정리해줘
```

주의할 점:

- Codex CLI의 비대화형 기본값은 read-only에 가까울 수 있습니다.
- Remote AI Coder는 기본으로 `--sandbox workspace-write`를 넘깁니다.
- `CODEX_SANDBOX` 또는 관리 UI의 `codex_sandbox`로 `read-only`, `workspace-write`, `danger-full-access`를 선택할 수 있습니다. `danger-full-access`는 신뢰된 환경에서만 사용하세요.

## Gemini CLI

설치 확인:

```bash
command -v gemini
```

설치가 필요하면:

```bash
npm install -g @google/gemini-cli
```

인증과 단독 실행:

```bash
gemini
cd /tmp
gemini --approval-mode yolo -p "Say hello in one line"
```

Remote AI Coder에서 사용:

```text
/model gemini
model: gemini README 문구를 더 간결하게 정리해줘
```

주의할 점:

- Gemini 인증은 서버 실행 계정에서 완료해야 합니다.
- `--approval-mode yolo`는 비대화형 변경을 허용하는 위험 옵션입니다. 허용 프로젝트, Telegram allowlist, Job worktree 격리가 적용된 환경에서만 사용하세요.
- 인증, 쿼터, 모델 접근 권한 문제는 Gemini CLI의 오류 메시지를 기준으로 확인하세요.

## Ollama

설치와 로컬 daemon을 확인합니다.

```bash
command -v ollama
ollama serve
ollama list
```

모델이 없으면 설치합니다.

```bash
ollama pull qwen2.5-coder:7b
```

Remote AI Coder에서 사용:

```text
/model ollama
/model ollama qwen2.5-coder:7b
ask: model: ollama Job 실행 파이프라인을 설명해줘
```

주의할 점:

- `/model ollama`는 로컬 Ollama 서버의 `/api/tags`를 조회해 탑재된 모델을 버튼으로 보여줍니다.
- 세부 모델을 선택하지 않으면 `REMOTE_CODER_OLLAMA_DEFAULT_MODEL` 또는 Ollama의 첫 번째 로컬 모델을 사용합니다.
- reply로 연결된 Ollama Job은 `~/.remote-coder/ollama_sessions/`에 로컬 transcript를 저장하고 최근 메시지를 다시 주입해 세션을 이어갑니다.
- PLAN, ASK, RESEARCH는 읽기 전용 prompt로 실행합니다. AGENT와 FIX는 best-effort입니다. 어댑터가 fenced unified diff block을 요청하고, 유효한 patch만 `git apply`로 적용합니다.
- Ollama에는 provider quota가 없으므로 `/monitor model`은 로컬 모델 상태와 응답에서 기록한 token count를 보여줍니다.

## 문제 해결

### CLI 명령을 찾을 수 없음

- 서버 실행 계정에서 `command -v claude`, `command -v codex`, `command -v gemini`, `command -v ollama`를 확인합니다.
- 셸 초기화 파일, PATH, 패키지 설치 위치가 서비스 실행 환경에도 적용되는지 확인합니다.

### Telegram 작업이 runner 단계에서 실패

- 먼저 같은 사용자 계정에서 CLI 단독 스모크 테스트를 실행합니다.
- `~/.remote-coder/worktrees/<project>/_logs/<job_id>.log`의 stdout/stderr 원문을 확인합니다.
- 인증 만료, 쿼터, 샌드박스, 권한 옵션을 우선 점검합니다.

### Worktree가 read-only로 실패

- OS 파일 권한 문제인지, CLI 샌드박스 문제인지 분리해서 확인해야 합니다.
- 단계별 점검은 [read-only worktree 가이드](read-only-workspace.ko.md)를 참고하세요.
