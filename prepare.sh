#!/bin/bash

# 에러 발생 시 스크립트 중단
set -e

echo "🚀 Remote AI Coder 환경 준비를 시작합니다..."

# 1. Conda 환경 설정 (Python 및 pip 의존성 설치)
if ! command -v conda &> /dev/null; then
    echo "❌ Conda가 설치되어 있지 않거나 PATH에 없습니다. Miniconda 또는 Anaconda를 먼저 설치해주세요."
    exit 1
fi

echo "📦 Conda 환경 'remote-coder' 설정 중..."
if conda info --envs | grep -q "^remote-coder "; then
    echo "환경이 이미 존재합니다. 업데이트를 진행합니다..."
    conda env update -f environment.yml
else
    echo "새로운 'remote-coder' 환경을 생성합니다..."
    conda env create -f environment.yml
fi

# 2. ngrok 설치 확인 및 안내
echo "📦 ngrok 확인 중..."
if ! command -v ngrok &> /dev/null; then
    echo "ngrok이 설치되어 있지 않습니다."
    if command -v npm &> /dev/null; then
        echo "npm을 통해 ngrok을 설치합니다..."
        npm install -g ngrok
    else
        echo "⚠️ npm을 찾을 수 없습니다. ngrok 홈페이지에서 수동으로 설치해주세요."
    fi
else
    echo "✅ ngrok이 이미 설치되어 있습니다."
fi

# 3. AI CLI 도구 설치 (Claude Code CLI, Codex CLI)
echo "📦 AI CLI 도구(Claude, Codex) 확인 중..."
if command -v npm &> /dev/null; then
    # Claude Code CLI 설치
    if ! command -v claude &> /dev/null; then
        echo "Claude Code CLI를 설치합니다..."
        npm install -g @anthropic-ai/claude-code
    else
        echo "✅ Claude Code CLI가 이미 설치되어 있습니다."
    fi

    # Codex CLI 설치
    if ! command -v codex &> /dev/null; then
        echo "Codex CLI를 설치합니다..."
        npm install -g @openai/codex
    else
        echo "✅ Codex CLI가 이미 설치되어 있습니다."
    fi
else
    echo "⚠️ npm이 설치되어 있지 않아 AI CLI 도구 설치를 건너뜁니다."
    echo "Node.js 및 npm 설치 후 다음 명령어들을 수동으로 실행하세요:"
    echo "npm install -g @anthropic-ai/claude-code"
    echo "npm install -g @openai/codex"
fi

# 4. .env 파일 준비
echo "📄 환경 변수 파일 확인 중..."
if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        cp .env.example .env
        echo "✅ .env.example 파일을 복사하여 .env 파일을 생성했습니다."
        echo "⚠️ 스크립트 완료 후 반드시 .env 파일을 열어 올바른 값으로 수정해주세요."
    else
        echo "⚠️ .env.example 파일을 찾을 수 없습니다."
    fi
else
    echo "✅ .env 파일이 이미 존재합니다."
fi

echo ""
echo "✨ 준비가 완료되었습니다!"
echo "다음 명령어를 실행하여 가상 환경을 활성화하세요:"
echo "conda activate remote-coder"
echo ""
echo "이후 ./run.sh 를 통해 서버를 실행할 수 있습니다."
