# Release Runbook

Remote AI Coder 릴리즈를 반복 가능하게 수행하기 위한 체크리스트입니다.  
현재 기준 공식 배포 채널은 **Git 태그 + GitHub Release**, 선택적으로 **PyPI**를 사용합니다.

## 1) 릴리즈 원칙

- 버전 규칙: `vMAJOR.MINOR.PATCH` (예: `v0.1.0`)
- 커밋 메시지 규칙: `chore: bump version to vX.Y.Z`
- 최소 변경 원칙: 버전 문자열·`CHANGELOG.md` 등 릴리즈 산출물만 수정
- 릴리즈 전 테스트 실패 상태에서는 태그 생성 금지

## 2) 사전 준비

- 로컬 브랜치가 최신 상태인지 확인
- Python/Conda 환경 확인
- 배포 계정 권한 확인
  - GitHub Release 권한
  - (선택) PyPI API Token

권장 명령:

```bash
git fetch --all --prune
git status
conda run -n remote-coder pytest -q
```

## 3) 버전 업데이트 (필수 3곳)

아래 세 파일의 버전을 동일하게 맞춥니다.

1. `pyproject.toml`  
   - `[project].version = "X.Y.Z"`
2. `app/__init__.py`  
   - `__version__ = "X.Y.Z"`
3. `tests/test_cli.py`  
   - `assert __version__ == "X.Y.Z"`

예: `0.1.0` 릴리즈 시 모두 `0.1.0`으로 통일

## 3b) CHANGELOG.md

Keep a Changelog 형식을 유지합니다.

- `[미배포]`에 쌓아 둔 항목이 있으면 새 버전 섹션 `## [X.Y.Z] — YYYY-MM-DD`로 옮기고, `[미배포]`는 비우거나 다음 릴리즈용 플레이스홀더만 남깁니다.
- 이번 릴리즈만 반영하는 추가·변경·수정·보안 요약을 사용자 관점으로 적습니다. 세부 커밋 나열은 생략하고 `git log`·GitHub Compare로 보완합니다.

## 4) 커밋 직전 체크리스트

- [ ] `pyproject.toml` 버전 업데이트
- [ ] `app/__init__.py` 버전 업데이트
- [ ] `tests/test_cli.py` 버전 assertion 업데이트
- [ ] `CHANGELOG.md`에 `[X.Y.Z]` 섹션 반영(및 `[미배포]` 정리)
- [ ] `git diff`로 버전·CHANGELOG 관련 파일만 바뀌었는지 확인
- [ ] `conda run -n remote-coder pytest -q` 통과 확인
- [ ] 커밋 메시지 `chore: bump version to vX.Y.Z` 사용

권장 명령:

```bash
git diff
conda run -n remote-coder pytest -q
git add pyproject.toml app/__init__.py tests/test_cli.py CHANGELOG.md
git commit -m "chore: bump version to vX.Y.Z"
```

## 5) 태그 및 GitHub Release

```bash
git tag -a vX.Y.Z -m "Release vX.Y.Z"
git push origin <release-branch>
git push origin vX.Y.Z
```

`v*.*.*` 태그가 원격에 푸시되면 `.github/workflows/release.yml`이 테스트·sdist/휠 빌드·`twine check` 후 GitHub Release를 만들고, 산출물(`*.tar.gz`, `*.whl`, `SHA256SUMS`)과 `CHANGELOG.md` 기반 릴리즈 노트를 첨부합니다. 로컬에서 태그만 올린 경우와 동일하게 동작합니다.

GitHub Release에는 다음 내용을 포함합니다.

- 버전: `vX.Y.Z`
- 변경 요약 (사용자 관점)
- 주의사항(브레이킹 변경 여부, 마이그레이션 필요 여부)
- 설치/업데이트 가이드 링크 (`README.md`)

## 6) (선택) PyPI 배포 절차

PyPI 배포가 필요한 경우에만 수행합니다.

```bash
python -m pip install --upgrade build twine
python -m build
twine check dist/*
```

테스트 업로드(TestPyPI):

```bash
twine upload --repository testpypi dist/*
```

실배포(PyPI):

```bash
twine upload dist/*
```

배포 후 설치 검증 예시:

```bash
python -m pip install --upgrade remote-coder==X.Y.Z
remote-coder --version
```

## 7) 릴리즈 후 검증

- 태그/Release 생성 확인
- `remote-coder --version` 결과 확인
- 핵심 명령 스모크 테스트
  - `remote-coder serve --help`
  - `remote-coder --version`

## 8) 롤백 가이드 (최소)

- 잘못된 태그만 생성된 경우: GitHub Release를 draft/삭제하고 원인 수정 후 새 태그 발행
- PyPI는 동일 버전 재업로드가 불가하므로 `PATCH` 버전을 올려 재배포
- 버전 불일치가 발견되면 3개 버전 파일을 다시 동기화 후 재검증

## 9) 빠른 실행 템플릿

```bash
# 1) 버전 수정 후 검증
git diff
conda run -n remote-coder pytest -q

# 2) 커밋/태그/푸시
git add pyproject.toml app/__init__.py tests/test_cli.py CHANGELOG.md
git commit -m "chore: bump version to vX.Y.Z"
git tag -a vX.Y.Z -m "Release vX.Y.Z"
git push origin <release-branch>
git push origin vX.Y.Z
```
