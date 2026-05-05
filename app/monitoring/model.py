from __future__ import annotations

import json
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final

from app.ai.usage import extract_runner_usage, format_token_usage, merge_token_usage
from app.jobs.schemas import Job
from app.models import ModelName

_CLI_TIMEOUT_SEC: Final[int] = 25
_RECENT_JOB_LIMIT: Final[int] = 50
_LOG_READ_LIMIT: Final[int] = 120_000


@dataclass(frozen=True)
class RecentUsageSummary:
    inspected_jobs: int
    latest_job_id: str | None = None
    latest_status: str | None = None
    latest_finished_at: datetime | None = None
    actual_model: str | None = None
    token_metrics: dict[str, int] | None = None


def format_model_monitor(
    model: ModelName,
    timeout_seconds: int = _CLI_TIMEOUT_SEC,
    *,
    recent_jobs: Iterable[Job] | None = None,
    chat_id: int | None = None,
    project: str | None = None,
) -> str:
    if model == ModelName.CLAUDE:
        body = _format_claude_monitor(timeout_seconds)
    elif model == ModelName.CODEX:
        body = _format_codex_monitor(timeout_seconds)
    else:
        body = _format_gemini_monitor(timeout_seconds)

    usage = _format_recent_usage_section(
        _summarize_recent_usage(recent_jobs, model=model, chat_id=chat_id, project=project)
    )
    if usage:
        return f"{body}\n\n{usage}"
    return body


def _summarize_recent_usage(
    recent_jobs: Iterable[Job] | None,
    *,
    model: ModelName,
    chat_id: int | None,
    project: str | None,
) -> RecentUsageSummary | None:
    if recent_jobs is None:
        return None

    matched: list[Job] = []
    for job in recent_jobs:
        if chat_id is not None and job.request.chat_id != chat_id:
            continue
        if project is not None and job.request.project != project:
            continue
        if job.request.model != model:
            continue
        matched.append(job)
        if len(matched) >= _RECENT_JOB_LIMIT:
            break

    if not matched:
        return RecentUsageSummary(inspected_jobs=0)

    latest = matched[0]
    actual_model: str | None = None
    totals: dict[str, int] = {}
    for job in matched:
        text = _read_observable_job_text(job)
        usage = extract_runner_usage(text)
        if actual_model is None:
            actual_model = job.runner_actual_model or usage.actual_model
        merge_token_usage(totals, job.runner_token_usage or usage.token_usage)

    return RecentUsageSummary(
        inspected_jobs=len(matched),
        latest_job_id=latest.id,
        latest_status=latest.status.value,
        latest_finished_at=latest.finished_at,
        actual_model=actual_model,
        token_metrics=totals or None,
    )


def _read_observable_job_text(job: Job) -> str:
    if job.log_path is not None:
        log_text = _read_log_excerpt(job.log_path)
        if log_text:
            return log_text
    parts = [job.runner_stdout_summary or "", job.runner_stderr_summary or ""]
    return "\n".join(part for part in parts if part)


def _read_log_excerpt(path: Path) -> str:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as file:
            return file.read(_LOG_READ_LIMIT)
    except OSError:
        return ""


def _format_recent_usage_section(summary: RecentUsageSummary | None) -> str | None:
    if summary is None:
        return None

    lines = ["최근 Job 사용량"]
    if summary.inspected_jobs == 0:
        lines.append("- 이 채팅/프로젝트/모델로 완료되거나 실행된 Job 기록이 아직 없습니다.")
        lines.append("- 실제 세부 모델명과 토큰은 CLI 출력·로컬 로그에 남은 경우에만 표시됩니다.")
        return "\n".join(lines)

    latest_bits = [summary.latest_job_id or "-"]
    if summary.latest_status:
        latest_bits.append(summary.latest_status)
    if summary.latest_finished_at:
        latest_bits.append(summary.latest_finished_at.isoformat())
    lines.append(f"- 최근 Job: {' / '.join(latest_bits)}")
    lines.append(f"- 확인한 Job 수: {summary.inspected_jobs}")
    if summary.actual_model:
        lines.append(f"- 관측된 세부 모델: {summary.actual_model}")
    else:
        lines.append("- 관측된 세부 모델: CLI 기본값/설정에서 자동 선택됨 (로그에서 확인 불가)")
    if summary.token_metrics:
        lines.append(f"- 관측된 토큰 합계: {format_token_usage(summary.token_metrics)}")
    else:
        lines.append("- 관측된 토큰 합계: 토큰 사용량 패턴을 로그에서 찾지 못했습니다.")
    lines.append("- 참고: 계정별 남은 한도/리셋 시각은 각 공급자 대시보드 또는 CLI 대화형 사용량 화면이 기준입니다.")
    return "\n".join(lines)


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
