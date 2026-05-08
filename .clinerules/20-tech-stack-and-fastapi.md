# 기술 스택과 FastAPI 구현 규칙

## 1. 권장 기술 스택

- Python 3.11 이상
- FastAPI
- Uvicorn
- pytest
- python-dotenv 또는 pydantic-settings
- pyproject.toml 기반 Python 패키징
- Telegram Bot API 직접 호출 또는 안정적인 Telegram 라이브러리
- Git CLI 기반 worktree 관리
- Claude Code CLI, Codex CLI, Gemini CLI 실행 래퍼

## 2. FastAPI 규칙

- Webhook 엔드포인트는 빠르게 응답해야 합니다.
- 시간이 오래 걸리는 AI 작업은 백그라운드 Job으로 넘깁니다.
- 라우터, 서비스, 설정, 모델을 분리합니다.
- 요청 검증에는 Pydantic 모델을 사용합니다.
- Webhook 요청 안에서 AI CLI를 직접 오래 실행하지 않습니다.

## 3. 설정 규칙

- 환경 변수는 `config.py` 또는 설정 객체에서 중앙 관리합니다.
- 프로젝트별 설정은 YAML/JSON 파일로 분리할 수 있게 설계합니다.
- 기본값은 안전한 값을 사용합니다.
- 새로운 환경 변수는 `.env.example`과 README에 함께 반영합니다.
- 테스트와 앱 실행 전에는 `conda activate remote-coder`로 프로젝트 전용 환경을 활성화합니다.

## 4. 패키징 규칙

- 공개 전 초기 패키지 버전은 `0.0.1`을 사용합니다.
- 설치형 실행 진입점은 `remote-coder` console script로 제공합니다.
- CLI/서버 도구는 Homebrew Cask보다 Formula 배포를 우선 검토합니다.
