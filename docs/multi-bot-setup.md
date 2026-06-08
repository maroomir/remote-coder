# 멀티봇·멀티프로젝트 설정 가이드

Remote Coder는 **등록된 프로젝트마다 별도의 Telegram 봇**을 두는 모델입니다. 채팅방에서 프로젝트를 바꾸는 `/project` 명령은 없으며, **어떤 봇과 대화하느냐가 곧 어떤 Git 저장소에 작업할지**를 결정합니다.

## 전제

- HTTPS로 공개 가능한 Base URL(예: ngrok)이 있어야 Telegram이 webhook을 호출할 수 있습니다.
- 프로젝트 메타데이터·봇 토큰·allowlist는 로컬 레지스트리 파일(`projects.json`)에 저장됩니다. 기본 경로는 `~/.remote-coder/projects.json`입니다(기존 `PROJECT_ROOT/.remote-coder/projects.json`이 있으면 하위호환으로 계속 읽습니다).

## 보안 주의

- `projects.json`에는 **BotFather 토큰이 평문**으로 들어갑니다. 파일 권한을 제한하고, 저장소에 커밋하지 마세요(`.gitignore`에 `.remote-coder/` 등이 포함되어 있는지 확인).
- 관리 UI와 `/api/*`는 **localhost 전용**으로 두세요. 토큰이 노출되면 해당 봇을 탈취당할 수 있습니다.
- 어드민 API 응답의 토큰은 마스킹되어 표시됩니다.

## 1. BotFather에서 봇 만들기

1. Telegram에서 [@BotFather](https://t.me/BotFather)를 엽니다.
2. `/newbot`으로 봇을 생성하고 **HTTP API 토큰**을 복사해 둡니다.
3. (선택) webhook 검증용으로 `secret_token`을 쓰려면 임의의 긴 문자열을 준비합니다. 프로젝트 레코드의 `webhook_secret`에 넣고, Telegram `setWebhook` 시 동일 값을 등록합니다.

프로젝트가 둘 이상이면 **프로젝트마다 봇을 하나씩** 만듭니다.

## 2. 관리 UI에서 프로젝트 등록

1. 서버를 띄운 뒤 같은 머신에서 `http://127.0.0.1:8000/projects` 로 이동합니다.
2. **프로젝트 이름**, **저장소 루트 경로**, **worktree 기준 디렉터리**, **기본 모델**을 입력합니다.
3. 해당 봇의 **bot_token**, (선택) **webhook_secret**, **허용 Chat ID**(최소 1개), (선택) **허용 User ID**를 입력합니다.
4. 저장하면 서버는 재시작 없이 해당 봇 인스턴스를 등록합니다.

`GET /api/projects` 응답에는 봇별 **`webhook_path`**(예: `/telegram/webhook/<16자리 16진 prefix>`), **`token_hash_prefix`**가 포함됩니다. 전체 webhook URL은 `<공개 HTTPS Base>` + `webhook_path` 입니다.

### Webhook URL과 토큰 해시

경로 마지막 세그먼트는 봇 토큰 문자열의 **SHA-256 16진 digest 앞 16자리**입니다. BotFather에서 토큰을 재발급하면 prefix가 바뀌므로 **Webhook URL도 다시 등록**해야 합니다.

## 3. Webhook 등록

공개 Base URL만 넘기면, **활성화(enabled)된** 모든 프로젝트에 대해 해당 봇 토큰으로 `setWebhook`을 호출합니다. `remote-coder up`은 ngrok 공개 URL로 이 등록을 자동 수행하므로 보통 별도 호출이 필요 없습니다. 외부 호스트의 고정 URL을 직접 등록하려면 다음을 사용하세요.

```bash
python scripts/set_webhook.py https://your-host.example
# 저장소에서 Conda로 개발 중이라면: conda activate remote-coder 후 위 명령 실행
```

각 프로젝트에 `webhook_secret`이 있으면 Telegram에 `secret_token`으로 함께 등록됩니다.

### 삭제·비활성화 후 Telegram 쪽 정리

레지스트리에서 프로젝트를 **삭제**하거나 **비활성**으로 두면, 서버는 그 토큰 해시 prefix에 해당하는 webhook 경로를 더 이상 매칭하지 않습니다(요청이 와도 처리되지 않거나 404). Telegram 클라우드에는 예전 webhook URL이 남을 수 있으므로, 완전히 끊거나 다른 서비스로 돌리려면 해당 봇에 대해 `deleteWebhook`을 호출하거나, 변경된 레지스트리 기준으로 `scripts/set_webhook.py`를 다시 실행해 URL을 맞추면 됩니다.

## 4. 채팅에서 사용하기

- 허용된 Chat/User로 해당 **봇과의 1:1 또는 그룹**에서 `/start`, 자연어 작업 요청 등을 사용합니다.
- 자연어 옵션은 `model:`, `branch:`, `no commit` 만 지원합니다. **`project:` 토큰은 없습니다.**
- `/init`은 이 채팅의 **기본 모델 오버라이드**와 **확인 대기 상태**만 초기화합니다. 봇에 묶인 프로젝트는 바뀌지 않습니다.

## 기존 단일 `.env` 사용자 마이그레이션

이전에는 `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_CHAT_IDS` 등이 필수였습니다. 현재는 **선택적 시드**입니다.

1. `.env`의 `DEFAULT_PROJECT`, `PROJECT_ROOT`와 선택적 `TELEGRAM_*`로 첫 부팅 시 `projects.json`이 비어 있으면 한 레코드가 시드될 수 있습니다. 워크트리는 `~/.remote-coder/worktrees/<project>/`에 자동 생성되어 경로 설정이 필요 없습니다.
2. 운영 환경에서는 관리 UI에서 **bot_token·allowlist·webhook_secret**을 프로젝트 단위로 채우는 것을 권장합니다.
3. 시드 후에는 토큰을 레지스트리에만 두고 `.env`에서 민감 값을 제거할 수 있습니다(로컬 정책에 맞게 결정).

자세한 환경 변수 설명은 저장소 루트의 [README.ko.md](../README.ko.md)와 [.env.example](../.env.example) 주석을 참고하세요.

## 장기 개선(참고)

토큰 평문 저장 대신 OS 키링·암호화 저장 등은 제품 로드맵에서 별도로 검토할 수 있습니다. 현재 MVP는 파일 기반 레지스트리를 사용합니다.
