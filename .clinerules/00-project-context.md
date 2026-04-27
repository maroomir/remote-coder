# 프로젝트 컨텍스트와 문서 역할

## 1. 프로젝트 목표

- Remote AI Coder는 텔레그램 메시지를 통해 로컬 개발 머신의 AI 코딩 도구를 원격 실행하고, 결과를 Git worktree/브랜치/커밋 단위로 안전하게 관리하는 시스템입니다.
- 모든 구현은 `PLAN.md`의 기획 의도, MVP 범위, 보안 원칙을 우선 기준으로 삼습니다.
- 초기 MVP는 “텔레그램 요청 수신 → 인증 → 작업 생성 → Git worktree 생성 → AI CLI 실행 → 커밋 → 결과 알림” 흐름을 완성하는 데 집중합니다.

## 2. 규칙 문서 역할 분리

이 프로젝트의 문서는 다음처럼 역할을 나눕니다.

| 문서 | 역할 | 주요 독자 |
|---|---|---|
| `PLAN.md` | 제품 기획, 요구사항, 범위, 로드맵 정의 | 사람, AI 에이전트 |
| `.clinerules/` | Cline이 자동으로 참고하는 프로젝트 전역 개발 규칙 | Cline, 개발자 |
| `.cursor/rules/` | Cursor가 참고하는 프로젝트 전역 개발 규칙 | Cursor, 개발자 |
| `AGENTS.md` | AI 에이전트가 작업을 수행할 때 따를 절차, 체크리스트, 완료 보고 기준 | AI 에이전트 |

`.clinerules/`와 `.cursor/rules/`는 “이 프로젝트에서 어떤 방식으로 개발해야 하는가”를 도구별 형식에 맞춰 주제별 규칙 파일로 정의하고, `AGENTS.md`는 “AI 에이전트가 실제 작업할 때 어떤 순서와 기준으로 행동해야 하는가”를 정의합니다.

## 3. Cline Rules 구조 원칙

- Cline 공식 규칙 구조에 맞춰 단일 `.clinerules` 파일보다 `.clinerules/` 디렉토리 안의 주제별 Markdown 파일을 사용합니다.
- 파일명은 정렬 순서를 고려해 숫자 prefix를 사용합니다.
- 새 규칙을 추가할 때는 기존 파일에 억지로 섞지 말고, 주제가 분명하면 별도 파일로 분리합니다.
- 규칙이 바뀌면 `AGENTS.md`, `PLAN.md`, README 등 관련 문서와 충돌하지 않는지 확인합니다.

## 4. Cursor Rules 구조 원칙

- Cursor 호환 규칙은 `.cursor/rules/` 디렉토리의 `.mdc` 파일로 관리합니다.
- 각 `.mdc` 파일은 Cursor 규칙 frontmatter(`description`, `globs`, `alwaysApply`)를 포함합니다.
- Cline 규칙과 Cursor 규칙은 같은 의도를 유지하되, 도구별 문법과 파일 구조만 다르게 관리합니다.
- `.clinerules/`를 수정할 때는 대응되는 `.cursor/rules/` 파일도 함께 검토합니다.

## 5. 작업 우선순위

1. FastAPI 앱 골격
2. 환경 설정 로딩
3. Telegram Webhook 수신
4. 사용자 allowlist 인증
5. Job 모델/상태 관리
6. Git worktree 서비스
7. Claude Runner
8. 결과 알림
9. Codex Runner
10. 테스트 및 문서 정리
