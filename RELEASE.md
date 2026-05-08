# Release Runbook

Remote AI Coder 릴리즈를 반복 가능하게 수행하기 위한 체크리스트입니다.  
현재 기준 공식 배포 채널은 **Git 태그 + GitHub Release**, 선택적으로 **PyPI**를 사용합니다.

## 1) 릴리즈 원칙

- 버전 규칙: `vMAJOR.MINOR.PATCH` (예: `v0.1.0`)
- 커밋 메시지 규칙: `chore: bump version to vX.Y.Z`
- 최소 변경 원칙: 버전 관련 파일만 수정
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

## 4) 커밋 직전 체크리스트

- [ ] `pyproject.toml` 버전 업데이트
- [ ] `app/__init__.py` 버전 업데이트
- [ ] `tests/test_cli.py` 버전 assertion 업데이트
- [ ] `git diff`로 버전 관련 파일만 바뀌었는지 확인
- [ ] `conda run -n remote-coder pytest -q` 통과 확인
- [ ] 커밋 메시지 `chore: bump version to vX.Y.Z` 사용

권장 명령:

```bash
git diff
conda run -n remote-coder pytest -q
git add pyproject.toml app/__init__.py tests/test_cli.py
git commit -m "chore: bump version to vX.Y.Z"
```

## 5) 태그 및 GitHub Release

```bash
git tag -a vX.Y.Z -m "Release vX.Y.Z"
git push origin <release-branch>
git push origin vX.Y.Z
```

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
git add pyproject.toml app/__init__.py tests/test_cli.py
git commit -m "chore: bump version to vX.Y.Z"
git tag -a vX.Y.Z -m "Release vX.Y.Z"
git push origin <release-branch>
git push origin vX.Y.Z
```
