#!/bin/bash

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
        echo "❌ Conda is not installed or not on PATH. Install Miniconda or Anaconda first."
        exit 1
    fi
}

setup_conda_env() {
    echo "📦 Setting up Conda environment 'remote-coder'..."
    if conda info --envs | grep -q "^remote-coder "; then
        echo "Environment already exists. Updating..."
        conda env update -f environment.yml
    else
        echo "Creating new 'remote-coder' environment..."
        conda env create -f environment.yml
    fi
}

ensure_ngrok() {
    echo "📦 Checking ngrok..."
    if command_exists ngrok; then
        echo "✅ ngrok is already installed."
        return
    fi

    echo "ngrok is not installed."
    if command_exists npm; then
        echo "Installing ngrok via npm..."
        npm install -g ngrok
    else
        echo "⚠️ npm not found. Install ngrok manually from the ngrok website."
    fi
}

install_npm_cli_if_missing() {
    local executable="$1"
    local package_name="$2"
    local display_name="$3"

    if command_exists "$executable"; then
        echo "✅ ${display_name} is already installed."
        return
    fi

    echo "Installing ${display_name}..."
    npm install -g "$package_name"
}

print_manual_ai_cli_install_commands() {
    echo "After installing Node.js and npm, run these commands manually:"
    for install_command in "${AI_CLI_INSTALL_COMMANDS[@]}"; do
        echo "$install_command"
    done
}

setup_ai_cli_tools() {
    echo "📦 Checking AI CLI tools (Claude, Codex, Gemini)..."
    if ! command_exists npm; then
        echo "⚠️ npm is not installed; skipping AI CLI tool installation."
        print_manual_ai_cli_install_commands
        return
    fi

    install_npm_cli_if_missing "claude" "@anthropic-ai/claude-code" "Claude Code CLI"
    install_npm_cli_if_missing "codex" "@openai/codex" "Codex CLI"
    install_npm_cli_if_missing "gemini" "@google/gemini-cli" "Gemini CLI"
}

print_next_steps() {
    echo ""
    echo "✨ Setup complete!"
    echo "Activate the environment:"
    echo "conda activate remote-coder"
    echo ""
    echo "Then run remote-coder up to start the server,"
    echo "and open http://127.0.0.1:8000/ in a browser to register your first project."
}

main() {
    echo "🚀 Starting Remote AI Coder environment setup..."
    ensure_conda_available
    setup_conda_env
    ensure_ngrok
    setup_ai_cli_tools
    print_next_steps
}

main "$@"
