#!/usr/bin/env bash
set -euo pipefail

# Dev workflow: editable install, ngrok tunnel, Telegram webhook registration, and --reload server.
# For local server only: `./scripts/dev.sh --no-tunnel`
# Production-style install: scripts/install.sh

ENV_NAME="${REMOTE_CODER_CONDA_ENV:-remote-coder}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

command -v conda >/dev/null 2>&1 || { echo "❌ conda is required (env: $ENV_NAME)"; exit 1; }
cd "$REPO_ROOT"

conda_run()      { conda run -n "$ENV_NAME" "$@"; }
conda_run_live() { conda run --no-capture-output -n "$ENV_NAME" "$@"; }

if ! conda_run python -m pip show remote-coder 2>/dev/null | grep -q "Editable project location"; then
    echo "📦 Applying editable install (pip install -e .[dev])..."
    conda_run_live python -m pip install -e ".[dev]"
fi

echo "🚀 Dev server (tunnel + webhook + reload)"
conda_run_live remote-coder up --reload "$@"
