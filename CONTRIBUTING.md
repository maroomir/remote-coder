# Contributing

기여해 주셔서 감사합니다. Remote AI Coder는 로컬 개발 머신에서 AI CLI와 Git 작업을 실행하는 도구이므로, 기능 추가보다 안전하고 테스트 가능한 변경을 우선합니다.

## 개발 환경

```bash
conda env create -f environment.yml
conda activate remote-coder
```

이미 환경이 있다면 다음처럼 테스트할 수 있습니다.

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 conda run -n remote-coder pytest -q -p pytest_asyncio.plugin -p respx.fixtures
```

`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`은 ROS 등 시스템 전역 pytest 플러그인이 Conda 환경 테스트에 끼어드는 것을 방지하기 위한 설정입니다.

## PR 전 체크리스트

- [ ] Bot Token, API key, Chat/User ID, 개인 경로, 로그 원문을 커밋하지 않았습니다.
- [ ] 외부 API, Git, 파일 시스템, subprocess 호출은 가능한 Adapter/서비스 계층에 격리했습니다.
- [ ] 사용자 입력을 shell 명령 문자열로 직접 실행하지 않았습니다.
- [ ] Telegram allowlist, webhook secret, 관리 UI localhost 제한 같은 보안 경계를 약화하지 않았습니다.
- [ ] Job은 기본 작업 트리가 아니라 요청별 Git worktree에서 실행되는 정책을 유지합니다.
- [ ] 변경된 동작에 대한 테스트를 추가하거나 갱신했습니다.
- [ ] 새 환경 변수·파일 기반 설정이나 명령어가 있으면 README와 관련 docs를 업데이트했습니다.
- [ ] 개발 규칙이나 작업 절차가 바뀌면 `.cursor/rules/`, `AGENTS.md` 동기화 필요성을 검토했습니다.

## 코드 스타일과 구조

- Python 3.11 이상을 기준으로 합니다.
- FastAPI 라우터, 설정, 서비스, 모델을 분리합니다.
- Claude/Codex/Gemini Runner는 공통 인터페이스 뒤에 두고 Strategy/Adapter 형태로 교체 가능하게 유지합니다.
- 복잡한 생성 로직은 Factory, 긴 작업 흐름은 Orchestrator/Facade로 분리하는 것을 검토합니다.
- 단순한 기능에 불필요한 패턴을 강제하지 않습니다.

## 테스트 원칙

- 기본 테스트는 실제 Telegram API, 실제 AI CLI, 실제 원격 Git push에 의존하지 않아야 합니다.
- 위험한 파일 삭제, 실제 커밋 생성, 외부 네트워크 호출은 mock 또는 fixture로 대체합니다.
- 우선 테스트 대상: 명령 파서, allowlist 인증, Job 상태 전이, Git worktree 서비스, Runner 결과 처리, Notifier 메시지 포맷입니다.