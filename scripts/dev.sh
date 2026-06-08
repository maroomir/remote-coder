#!/usr/bin/env bash
set -euo pipefail

# 개발용: 소스를 editable로 설치해 수정이 즉시 반영되게 하고, 터널/webhook 없이
# --reload 로 서버를 실행한다. 배포용 설치는 scripts/install.sh 가 담당한다.

ENV_NAME="${REMOTE_CODER_CONDA_ENV:-remote-coder}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

command -v conda >/dev/null 2>&1 || { echo "❌ conda 가 필요합니다 (환경: $ENV_NAME)"; exit 1; }
cd "$REPO_ROOT"

conda_run()      { conda run -n "$ENV_NAME" "$@"; }
conda_run_live() { conda run --no-capture-output -n "$ENV_NAME" "$@"; }

if ! conda_run python -m pip show remote-coder 2>/dev/null | grep -q "Editable project location"; then
    echo "📦 editable 설치 적용 중 (pip install -e .[dev])..."
    conda_run_live python -m pip install -e ".[dev]"
fi

echo "🚀 개발 서버 (no-tunnel, reload)"
conda_run_live remote-coder up --no-tunnel --reload "$@"
