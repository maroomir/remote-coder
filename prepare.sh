#!/bin/bash

# 에러 발생 시 스크립트 중단
set -e

AI_CLI_INSTALL_COMMANDS=(
    "npm install -g @anthropic-ai/claude-code"
    "npm install -g @openai/codex"
    "npm install -g @google/gemini-cli"
)

command_exists() {
    command -v "$1" &> /dev/null
}

ensure_conda_available() {
    if ! command_exists conda; then
        echo "❌ Conda가 설치되어 있지 않거나 PATH에 없습니다. Miniconda 또는 Anaconda를 먼저 설치해주세요."
        exit 1
    fi
}

setup_conda_env() {
    echo "📦 Conda 환경 'remote-coder' 설정 중..."
    if conda info --envs | grep -q "^remote-coder "; then
        echo "환경이 이미 존재합니다. 업데이트를 진행합니다..."
        conda env update -f environment.yml
    else
        echo "새로운 'remote-coder' 환경을 생성합니다..."
        conda env create -f environment.yml
    fi
}

ensure_ngrok() {
    echo "📦 ngrok 확인 중..."
    if command_exists ngrok; then
        echo "✅ ngrok이 이미 설치되어 있습니다."
        return
    fi

    echo "ngrok이 설치되어 있지 않습니다."
    if command_exists npm; then
        echo "npm을 통해 ngrok을 설치합니다..."
        npm install -g ngrok
    else
        echo "⚠️ npm을 찾을 수 없습니다. ngrok 홈페이지에서 수동으로 설치해주세요."
    fi
}

install_npm_cli_if_missing() {
    local executable="$1"
    local package_name="$2"
    local display_name="$3"

    if command_exists "$executable"; then
        echo "✅ ${display_name}가 이미 설치되어 있습니다."
        return
    fi

    echo "${display_name}를 설치합니다..."
    npm install -g "$package_name"
}

print_manual_ai_cli_install_commands() {
    echo "Node.js 및 npm 설치 후 다음 명령어들을 수동으로 실행하세요:"
    for install_command in "${AI_CLI_INSTALL_COMMANDS[@]}"; do
        echo "$install_command"
    done
}

setup_ai_cli_tools() {
    echo "📦 AI CLI 도구(Claude, Codex, Gemini) 확인 중..."
    if ! command_exists npm; then
        echo "⚠️ npm이 설치되어 있지 않아 AI CLI 도구 설치를 건너뜁니다."
        print_manual_ai_cli_install_commands
        return
    fi

    install_npm_cli_if_missing "claude" "@anthropic-ai/claude-code" "Claude Code CLI"
    install_npm_cli_if_missing "codex" "@openai/codex" "Codex CLI"
    install_npm_cli_if_missing "gemini" "@google/gemini-cli" "Gemini CLI"
}

prepare_env_file() {
    echo "📄 환경 변수 파일 확인 중..."
    if [ -f .env ]; then
        echo "✅ .env 파일이 이미 존재합니다."
        return
    fi

    if [ -f .env.example ]; then
        cp .env.example .env
        echo "✅ .env.example 파일을 복사하여 .env 파일을 생성했습니다."
        echo "⚠️ 스크립트 완료 후 반드시 .env 파일을 열어 올바른 값으로 수정해주세요."
    else
        echo "⚠️ .env.example 파일을 찾을 수 없습니다."
    fi
}

print_next_steps() {
    echo ""
    echo "✨ 준비가 완료되었습니다!"
    echo "다음 명령어를 실행하여 가상 환경을 활성화하세요:"
    echo "conda activate remote-coder"
    echo ""
    echo "이후 ./run.sh 를 통해 서버를 실행할 수 있습니다."
}

main() {
    echo "🚀 Remote AI Coder 환경 준비를 시작합니다..."
    ensure_conda_available
    setup_conda_env
    ensure_ngrok
    setup_ai_cli_tools
    prepare_env_file
    print_next_steps
}

main "$@"
