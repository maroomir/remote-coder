#!/usr/bin/env bash
set -euo pipefail

# 개발용: 소스를 editable로 설치해 수정이 즉시 반영되게 하고, ngrok 터널 +
# Telegram webhook 등록 + --reload 서버를 한 번에 실행한다(옛 run.sh 동작).
# 터널 없이 로컬 서버만 띄우려면 `./scripts/dev.sh --no-tunnel` 로 호출한다.
# 배포용 설치는 scripts/install.sh 가 담당한다.

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

echo "🚀 개발 서버 (tunnel + webhook + reload)"
conda_run_live remote-coder up --reload "$@"
