#!/usr/bin/env bash
set -euo pipefail

# PyPI 공개 전에는 git 소스에서 설치합니다. 공개 후에는 REMOTE_CODER_REPO 를 패키지명으로 바꾸세요.
REPO_URL="${REMOTE_CODER_REPO:-git+https://github.com/maroomir/remote-coder.git}"

info() { printf '\033[0;34m%s\033[0m\n' "$*"; }
ok()   { printf '\033[0;32m%s\033[0m\n' "$*"; }
warn() { printf '\033[0;33m%s\033[0m\n' "$*"; }
err()  { printf '\033[0;31m%s\033[0m\n' "$*" >&2; }

command_exists() { command -v "$1" >/dev/null 2>&1; }

ensure_uv() {
    if command_exists uv; then
        ok "✅ uv 발견"
        return
    fi
    info "📦 uv 설치 중..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
    if ! command_exists uv; then
        err "uv 설치에 실패했습니다. https://docs.astral.sh/uv/ 를 참고해 수동 설치하세요."
        exit 1
    fi
}

install_remote_coder() {
    info "📦 remote-coder 설치 중... ($REPO_URL)"
    uv tool install --force "$REPO_URL"
}

ensure_path_hint() {
    case ":$PATH:" in
        *":$HOME/.local/bin:"*) ;;
        *) warn "⚠️ \$HOME/.local/bin 이 PATH에 없습니다. 셸 설정에 추가하세요: export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
    esac
}

verify() {
    if command_exists remote-coder; then
        ok "✅ 설치 완료: $(remote-coder --version)"
    else
        warn "⚠️ remote-coder 명령을 PATH에서 찾지 못했습니다. 새 터미널을 열거나 PATH를 갱신하세요."
    fi
}

check_prereqs() {
    info "🔎 전제조건 점검:"
    if command_exists ngrok; then
        ok "  ✅ ngrok"
    else
        warn "  ⚠️ ngrok 미설치 — https://ngrok.com/download (설치 후 ngrok config add-authtoken <token>)"
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
        warn "  ⚠️ AI CLI 미설치 — 최소 1개 필요 (예: npm install -g @anthropic-ai/claude-code)"
    fi
}

main() {
    info "🚀 Remote AI Coder 설치를 시작합니다..."
    if ! command_exists curl; then
        err "curl 이 필요합니다."
        exit 1
    fi
    ensure_uv
    install_remote_coder
    ensure_path_hint
    verify
    check_prereqs

    echo
    ok "다음 단계:"
    echo "  1) remote-coder up                 # 터널 + webhook + 서버 실행"
    echo "  2) http://127.0.0.1:8000/ 접속      # 최초 설정 카드에서 첫 프로젝트 등록"
}

main "$@"
