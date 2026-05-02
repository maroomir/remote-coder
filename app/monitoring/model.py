"""Claude/Codex/Gemini CLI Probe — 비대화형으로 조회 가능한 정보만 표시."""

from __future__ import annotations

import json
import subprocess
from typing import Final

from app.models import ModelName

_CLI_TIMEOUT_SEC: Final[int] = 25


def format_model_monitor(model: ModelName, timeout_seconds: int = _CLI_TIMEOUT_SEC) -> str:
    """현재 선택 모델 기준 CLI 상태 요약."""
    if model == ModelName.CLAUDE:
        return _format_claude_monitor(timeout_seconds)
    if model == ModelName.CODEX:
        return _format_codex_monitor(timeout_seconds)
    return _format_gemini_monitor(timeout_seconds)


def _format_claude_monitor(timeout_seconds: int) -> str:
    lines: list[str] = ["[Claude]"]
    try:
        proc = subprocess.run(
            ["claude", "auth", "status", "--text"],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            shell=False,
        )
    except FileNotFoundError:
        lines.append("CLI: `claude` 명령을 찾을 수 없습니다. Claude Code CLI 설치 및 PATH를 확인하세요.")
        lines.extend(_claude_footer())
        return "\n".join(lines)
    except subprocess.TimeoutExpired:
        lines.append("`claude auth status --text` 시간 초과.")
        lines.extend(_claude_footer())
        return "\n".join(lines)

    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if proc.returncode == 0 and out:
        snippet = out if len(out) <= 2500 else out[:2500].rstrip() + "\n...(생략)"
        lines.append("auth status (--text):")
        lines.append(snippet)
    else:
        lines.extend(_claude_auth_fallback_json(timeout_seconds, proc.returncode, err or out))

    lines.extend(_claude_footer())
    return "\n".join(lines)


def _claude_auth_fallback_json(timeout_seconds: int, prev_code: int, prev_msg: str) -> list[str]:
    lines: list[str] = []
    try:
        proc = subprocess.run(
            ["claude", "auth", "status"],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            shell=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        lines.append(f"auth status 실패 (이전 exit {prev_code}): {prev_msg[:400]}")
        return lines

    raw = (proc.stdout or "").strip()
    if proc.returncode != 0 or not raw:
        lines.append(f"auth status 실패 (exit {proc.returncode}): {(proc.stderr or prev_msg)[:400]}")
        return lines
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        lines.append("auth status: JSON이 아닌 출력입니다 (처음 400자).")
        lines.append(raw[:400])
        return lines

    safe_keys = (
        "logged_in",
        "authenticated",
        "account",
        "email",
        "subscription",
        "plan",
        "organization",
    )
    picked: dict[str, object] = {}
    if isinstance(data, dict):
        for k in safe_keys:
            if k in data:
                picked[k] = data[k]
        lines.append("auth status (JSON 요약, 민감값 제외):")
        lines.append(json.dumps(picked, ensure_ascii=False, indent=2) if picked else "{}")
    else:
        lines.append("auth status: 예상과 다른 JSON 형식입니다.")
    return lines


def _claude_footer() -> list[str]:
    return [
        "",
        "참고: 구독·요금제별 남은 할당량·윈도우 리셋 시각은 Claude Code 대화형 `/usage`(또는 `/cost`) 또는",
        "Anthropic 계정 대시보드에서 확인하는 것이 가장 정확합니다.",
    ]


def _format_codex_monitor(timeout_seconds: int) -> str:
    lines: list[str] = ["[Codex]"]
    try:
        proc = subprocess.run(
            ["codex", "--version"],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            shell=False,
        )
    except FileNotFoundError:
        lines.append("CLI: `codex` 명령을 찾을 수 없습니다. Codex CLI 설치 및 PATH를 확인하세요.")
        lines.extend(_codex_footer())
        return "\n".join(lines)
    except subprocess.TimeoutExpired:
        lines.append("`codex --version` 시간 초과.")
        lines.extend(_codex_footer())
        return "\n".join(lines)

    ver = (proc.stdout or proc.stderr or "").strip()
    if ver:
        snippet = ver if len(ver) <= 500 else ver[:500] + "..."
        lines.append(f"CLI 버전:\n{snippet}")
    else:
        lines.append(f"버전 확인 실패 (exit {proc.returncode}).")

    lines.extend(_codex_footer())
    return "\n".join(lines)


def _codex_footer() -> list[str]:
    return [
        "",
        "참고: Codex CLI는 계정별 남은 크레딧·플랜 한도를 터미널 한 줄로 조회하는 공식 서브커맨드가",
        "환경에 따라 제한적일 수 있습니다 (OpenAI 측 로드맵 이슈 참고).",
        "웹 사용량: https://chatgpt.com/codex/settings/usage",
        "세션별 토큰 이벤트는 로컬 CODEX_HOME(기본 ~/.codex) 세션 로그에 기록될 수 있습니다.",
    ]


def _format_gemini_monitor(timeout_seconds: int) -> str:
    lines: list[str] = ["[Gemini]"]
    try:
        proc = subprocess.run(
            ["gemini", "--version"],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            shell=False,
        )
    except FileNotFoundError:
        lines.append("CLI: `gemini` 명령을 찾을 수 없습니다. Gemini CLI 설치 및 PATH를 확인하세요.")
        lines.extend(_gemini_footer())
        return "\n".join(lines)
    except subprocess.TimeoutExpired:
        lines.append("`gemini --version` 시간 초과.")
        lines.extend(_gemini_footer())
        return "\n".join(lines)

    ver = (proc.stdout or proc.stderr or "").strip()
    if ver:
        snippet = ver if len(ver) <= 500 else ver[:500] + "..."
        lines.append(f"CLI 버전:\n{snippet}")
    else:
        lines.append(f"버전 확인 실패 (exit {proc.returncode}).")

    lines.extend(_gemini_footer())
    return "\n".join(lines)


def _gemini_footer() -> list[str]:
    return [
        "",
        "설치: npm install -g @google/gemini-cli",
        "참고: 인증과 quota는 `gemini` 대화형 `/auth` 또는 Google/Gemini 계정 화면에서 확인하세요.",
        "문서: https://geminicli.com/docs/get-started/installation/",
    ]
