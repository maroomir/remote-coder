#!/usr/bin/env bash
set -euo pipefail

# Before PyPI release: install from git source. After release, set REMOTE_CODER_REPO to the package name.
REPO_URL="${REMOTE_CODER_REPO:-git+https://github.com/maroomir/remote-coder.git}"

info() { printf '\033[0;34m%s\033[0m\n' "$*"; }
ok()   { printf '\033[0;32m%s\033[0m\n' "$*"; }
warn() { printf '\033[0;33m%s\033[0m\n' "$*"; }
err()  { printf '\033[0;31m%s\033[0m\n' "$*" >&2; }

command_exists() { command -v "$1" >/dev/null 2>&1; }

ensure_uv() {
    if command_exists uv; then
        ok "✅ uv found"
        return
    fi
    info "📦 Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
    if ! command_exists uv; then
        err "Failed to install uv. See https://docs.astral.sh/uv/ for manual installation."
        exit 1
    fi
}

install_remote_coder() {
    info "📦 Installing remote-coder... ($REPO_URL)"
    uv tool install --force "$REPO_URL"
}

ensure_path_hint() {
    case ":$PATH:" in
        *":$HOME/.local/bin:"*) ;;
        *) warn "⚠️ \$HOME/.local/bin is not on PATH. Add to your shell config: export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
    esac
}

verify() {
    if command_exists remote-coder; then
        ok "✅ Installed: $(remote-coder --version)"
    else
        warn "⚠️ remote-coder not found on PATH. Open a new terminal or refresh PATH."
    fi
}

check_prereqs() {
    info "🔎 Prerequisite checks:"
    if command_exists ngrok; then
        ok "  ✅ ngrok"
    else
        warn "  ⚠️ ngrok not installed — https://ngrok.com/download (then ngrok config add-authtoken <token>)"
    fi

    local found=""
    for tool in claude codex gemini; do
        if command_exists "$tool"; then
            found="$found $tool"
        fi
    done
    if [ -n "$found" ]; then
        ok "  ✅ AI CLI:$found"
    else
        warn "  ⚠️ AI CLI not installed — at least one required (e.g. npm install -g @anthropic-ai/claude-code)"
    fi
}

main() {
    info "🚀 Starting Remote AI Coder installation..."
    if ! command_exists curl; then
        err "curl is required."
        exit 1
    fi
    ensure_uv
    install_remote_coder
    ensure_path_hint
    verify
    check_prereqs

    echo
    ok "Next steps:"
    echo "  1) remote-coder up                 # tunnel + webhook + server"
    echo "  2) open http://127.0.0.1:8000/     # register your first project in the setup card"
}

main "$@"
