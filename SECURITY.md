# Security Policy

Remote AI Coder는 Telegram 메시지를 통해 로컬 머신의 AI CLI와 Git 작업을 실행합니다. 일반적인 웹 애플리케이션보다 로컬 파일 시스템, Git 원격 저장소, AI CLI 권한과 관련된 위험이 큽니다.

## 지원 범위

현재 프로젝트는 초기 MVP 단계입니다. 공개 저장소의 기본 브랜치 최신 버전을 기준으로 보안 제보를 받습니다.

## 취약점 제보

보안 취약점이 의심되면 공개 Issue에 토큰, Chat ID, 로그 원문, 개인 경로를 올리지 마세요.

- GitHub Security Advisory의 비공개 제보 기능을 사용할 수 있으면 우선 사용해 주세요.
- 사용할 수 없는 경우, 저장소 관리자에게 비공개 채널로 재현 절차와 영향을 전달해 주세요.

## 운영 보안 체크리스트

- Telegram Bot Token, webhook secret, AI API key, 개인 Chat/User ID를 커밋하지 않습니다.
- 봇 토큰과 webhook secret은 OS 키링(macOS Keychain / Linux Secret Service / Windows Credential Locker)에 저장됩니다. 키링이 있는 환경에서 처음 실행하면 평문 `projects.json` 시크릿이 키링으로 1회 이전되고 `projects.json.pre-keyring.bak`로 백업되므로, **이전이 정상 동작하고 평문이 파일에서 사라졌는지 확인한 뒤 백업 파일을 안전하게 삭제**합니다. 키링으로 이전한 호스트는 부팅 시 키링 접근이 필요하므로, 키링 잠금 해제 상태를 유지합니다.
- 키링 백엔드가 없는 headless 환경에서는 신규 설치가 fail-closed로 중단됩니다. 의도적으로 평문 저장을 허용하려면 `REMOTE_CODER_ALLOW_PLAINTEXT_SECRETS=1`을 설정하되, 그 경우 `projects.json` 권한(owner-only)과 백업·커밋 제외를 엄격히 합니다.
- 릴리스 전 수동 점검(자동 테스트로 못 잡는 항목): 지원 OS별로 토큰 등록 → 재시작 → 복원 round-trip이 일치하는지, 프로젝트 삭제 후 해당 키링 항목이 정리되는지 실제 키링에서 확인합니다.
- private 저장소를 public으로 전환하기 전 Git 전체 히스토리를 secret scan 합니다.
- 기존 private 기간에 사용한 Bot Token과 webhook secret은 공개 전 재발급합니다.
- `TELEGRAM_ALLOWED_CHAT_IDS` 또는 `TELEGRAM_ALLOWED_USER_IDS` allowlist를 반드시 설정합니다.
- Telegram webhook secret을 설정하고, `scripts/set_webhook.py`로 `secret_token`이 함께 등록되었는지 확인합니다. 관리 UI에서 새 프로젝트를 만들 때 비워 두면 고유한 256비트 secret이 자동 생성됩니다.
- 관리 UI와 API(`/`, `/projects`, `/advanced`, `/logs`, `/database`, `/api/*`)를 외부에 노출하지 않습니다.
- ngrok/reverse proxy는 Telegram webhook 경로(`/telegram/webhook`)에만 접근 가능하도록 제한하는 구성을 권장합니다.
- 대상 프로젝트 경로와 worktree 경로는 신뢰 가능한 로컬 경로로 제한합니다.
- Claude `--dangerously-skip-permissions`, Gemini `--approval-mode yolo`, Codex `danger-full-access` 사용 전 위험성을 이해하고, 개인 실험용 환경에서만 사용합니다.
- SQLite 대화 기억에는 사용자 메시지와 Job 결과 요약이 저장될 수 있으므로 민감정보를 Telegram 메시지에 포함하지 않습니다.

## 공개 전 권장 점검 명령

```bash
git status --short
git ls-files | grep -E '(^|/)(\.env|.*\.sqlite3|.*\.db|.*\.log|\.remote-coder/|worktrees/|projects\.(json|ya?ml))$' || true
git log --all -p -- . ':!LICENSE' | grep -Ei 'bot[0-9]+:|telegram.*token|api[_-]?key|secret|password' || true
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 conda run -n remote-coder pytest -q -p pytest_asyncio.plugin -p respx.fixtures
```

가능하면 `gitleaks`, `trufflehog` 같은 전용 secret scanner도 함께 사용하세요.
