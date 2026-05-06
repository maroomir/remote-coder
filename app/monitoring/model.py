from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final

from app.ai.usage import extract_runner_usage, format_token_usage, merge_token_usage
from app.jobs.schemas import Job
from app.models import ModelName

_CLI_TIMEOUT_SEC: Final[int] = 25
_RECENT_JOB_LIMIT: Final[int] = 50
_LOG_READ_LIMIT: Final[int] = 120_000
_LOCAL_USAGE_FILE_LIMIT: Final[int] = 80
_LOCAL_USAGE_LINE_LIMIT: Final[int] = 5000


@dataclass(frozen=True)
class RecentUsageSummary:
    inspected_jobs: int
    latest_job_id: str | None = None
    latest_status: str | None = None
    latest_finished_at: datetime | None = None
    actual_model: str | None = None
    token_metrics: dict[str, int] | None = None


@dataclass(frozen=True)
class LocalQuotaWindow:
    label: str
    used_percent: float
    remaining_percent: float
    resets_at: datetime | None = None


@dataclass(frozen=True)
class LocalUsageSnapshot:
    source: str
    observed_at: datetime | None = None
    actual_model: str | None = None
    token_metrics: dict[str, int] | None = None
    quota_windows: tuple[LocalQuotaWindow, ...] = ()
    plan_type: str | None = None
    requests_today: int | None = None
    remaining_note: str | None = None


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

    local_usage = _format_local_usage_section(_read_local_usage_snapshot(model))
    usage = _format_recent_usage_section(
        _summarize_recent_usage(recent_jobs, model=model, chat_id=chat_id, project=project)
    )
    sections = [body]
    if local_usage:
        sections.append(local_usage)
    if usage:
        sections.append(usage)
    return "\n\n".join(sections)


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
    return "\n".join(lines)


def _read_local_usage_snapshot(model: ModelName) -> LocalUsageSnapshot | None:
    if model == ModelName.CLAUDE:
        return _read_claude_local_usage()
    if model == ModelName.CODEX:
        return _read_codex_local_usage()
    return _read_gemini_local_usage()


def _format_local_usage_section(snapshot: LocalUsageSnapshot | None) -> str | None:
    if snapshot is None:
        return "실제 로컬 사용량/잔여량\n- 로컬 CLI 사용량 로그를 찾지 못했습니다."

    lines = ["실제 로컬 사용량/잔여량", f"- 출처: {snapshot.source}"]
    if snapshot.observed_at:
        lines.append(f"- 관측 시각: {snapshot.observed_at.astimezone().isoformat(timespec='seconds')}")
    if snapshot.plan_type:
        lines.append(f"- 플랜/계정 유형: {snapshot.plan_type}")
    if snapshot.actual_model:
        lines.append(f"- 관측된 세부 모델: {snapshot.actual_model}")
    if snapshot.token_metrics:
        formatted = format_token_usage(snapshot.token_metrics)
        if formatted:
            lines.append(f"- 관측된 토큰: {formatted}")
    if snapshot.requests_today is not None:
        lines.append(f"- 오늘 로컬 로그 기준 요청 수: {snapshot.requests_today:,}")
    if snapshot.quota_windows:
        for window in snapshot.quota_windows:
            reset = ""
            if window.resets_at is not None:
                reset = f", 리셋 {window.resets_at.astimezone().isoformat(timespec='minutes')}"
            lines.append(
                f"- {window.label}: 잔여 {window.remaining_percent:g}% "
                f"(사용 {window.used_percent:g}%{reset})"
            )
    elif snapshot.remaining_note:
        lines.append(f"- 잔여량: {snapshot.remaining_note}")
    return "\n".join(lines)


def _read_codex_local_usage() -> LocalUsageSnapshot | None:
    root = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    sessions = root / "sessions"
    newest: tuple[Path, dict[str, Any], datetime | None] | None = None
    for path in _iter_recent_files(sessions, "*.jsonl"):
        for item in _read_jsonl_objects(path):
            payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
            if not isinstance(payload, dict):
                continue
            if "rate_limits" not in payload and "info" not in payload:
                continue
            observed = _parse_datetime(item.get("timestamp"))
            if _is_newer(observed, newest[2] if newest else None):
                newest = (path, item, observed)
    if newest is None:
        return None

    path, item, observed = newest
    payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
    info = payload.get("info") if isinstance(payload.get("info"), dict) else {}
    rate_limits = payload.get("rate_limits") if isinstance(payload.get("rate_limits"), dict) else {}
    token_usage = _normalize_token_dict(info.get("total_token_usage"))
    windows = _codex_quota_windows(rate_limits)
    return LocalUsageSnapshot(
        source=_compact_home(path),
        observed_at=observed,
        token_metrics=token_usage or None,
        quota_windows=tuple(windows),
        plan_type=_string_or_none(rate_limits.get("plan_type")),
        remaining_note=None if windows else "Codex 세션 로그에서 rate_limits 스냅샷을 찾지 못했습니다.",
    )


def _codex_quota_windows(rate_limits: dict[str, Any]) -> list[LocalQuotaWindow]:
    windows: list[LocalQuotaWindow] = []
    for key, fallback in (("primary", "기본 윈도우"), ("secondary", "보조 윈도우")):
        raw = rate_limits.get(key)
        if not isinstance(raw, dict):
            continue
        used = _float_or_none(raw.get("used_percent"))
        if used is None:
            continue
        minutes = _int_or_none(raw.get("window_minutes"))
        label = _format_window_label(minutes) if minutes is not None else fallback
        windows.append(
            LocalQuotaWindow(
                label=label,
                used_percent=used,
                remaining_percent=max(0.0, 100.0 - used),
                resets_at=_datetime_from_epoch(raw.get("resets_at")),
            )
        )
    return windows


def _read_claude_local_usage() -> LocalUsageSnapshot | None:
    root = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
    projects = root / "projects"
    newest: tuple[Path, dict[str, Any], dict[str, Any], datetime | None] | None = None
    for path in _iter_recent_files(projects, "*.jsonl"):
        for item in _read_jsonl_objects(path):
            message = item.get("message") if isinstance(item.get("message"), dict) else {}
            usage = message.get("usage") if isinstance(message.get("usage"), dict) else {}
            if usage:
                observed = _parse_datetime(item.get("timestamp"))
                if _is_newer(observed, newest[3] if newest else None):
                    newest = (path, item, message, observed)
    if newest is None:
        return None

    path, _item, message, observed = newest
    return LocalUsageSnapshot(
        source=_compact_home(path),
        observed_at=observed,
        actual_model=_string_or_none(message.get("model")),
        token_metrics=_normalize_token_dict(message.get("usage")) or None,
        remaining_note="Claude 로컬 transcript에는 세션 토큰은 남지만 계정 잔여 quota 스냅샷은 저장되지 않았습니다.",
    )


def _read_gemini_local_usage() -> LocalUsageSnapshot | None:
    root = Path(os.environ.get("GEMINI_HOME", Path.home() / ".gemini"))
    newest: tuple[Path, dict[str, Any], datetime | None] | None = None
    today = datetime.now().astimezone().date()
    requests_today = 0
    for path in _iter_recent_files(root, "*.jsonl"):
        for item in _read_jsonl_objects(path):
            if item.get("type") != "gemini" or not isinstance(item.get("tokens"), dict):
                continue
            observed = _parse_datetime(item.get("timestamp"))
            if observed and observed.astimezone().date() == today:
                requests_today += 1
            if _is_newer(observed, newest[2] if newest else None):
                newest = (path, item, observed)
    if newest is None:
        return None

    path, item, observed = newest
    return LocalUsageSnapshot(
        source=_compact_home(path),
        observed_at=observed,
        actual_model=_string_or_none(item.get("model")),
        token_metrics=_normalize_token_dict(item.get("tokens")) or None,
        requests_today=requests_today,
        remaining_note="Gemini 로컬 chat 로그에는 요청·토큰은 남지만 계정 잔여 quota 스냅샷은 저장되지 않았습니다.",
    )


def _iter_recent_files(root: Path, pattern: str) -> list[Path]:
    if not root.exists():
        return []
    try:
        files = [p for p in root.rglob(pattern) if p.is_file()]
    except OSError:
        return []
    files.sort(key=lambda p: _safe_mtime(p), reverse=True)
    return files[:_LOCAL_USAGE_FILE_LIMIT]


def _read_jsonl_objects(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []

    objects: list[dict[str, Any]] = []
    for line in lines[-_LOCAL_USAGE_LINE_LIMIT:]:
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            objects.append(item)
    return objects


def _normalize_token_dict(raw: object) -> dict[str, int]:
    if not isinstance(raw, dict):
        return {}
    labels = {
        "input_tokens": "input",
        "cache_creation_input_tokens": "cache write",
        "cache_read_input_tokens": "cache read",
        "cached_input_tokens": "cached",
        "output_tokens": "output",
        "reasoning_output_tokens": "reasoning",
        "total_tokens": "total",
        "input": "input",
        "output": "output",
        "cached": "cached",
        "thoughts": "thoughts",
        "tool": "tool",
        "total": "total",
    }
    metrics: dict[str, int] = {}
    for key, value in raw.items():
        normalized = labels.get(str(key))
        parsed = _int_or_none(value)
        if normalized is not None and parsed is not None:
            metrics[normalized] = metrics.get(normalized, 0) + parsed
    return metrics


def _parse_datetime(raw: object) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _datetime_from_epoch(raw: object) -> datetime | None:
    value = _int_or_none(raw)
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(value, tz=timezone.utc)
    except (OSError, ValueError, OverflowError):
        return None


def _format_window_label(minutes: int) -> str:
    if minutes == 300:
        return "5시간 한도"
    if minutes == 10080:
        return "주간 한도"
    if minutes % 1440 == 0:
        return f"{minutes // 1440}일 한도"
    if minutes % 60 == 0:
        return f"{minutes // 60}시간 한도"
    return f"{minutes}분 한도"


def _compact_home(path: Path) -> str:
    home = Path.home()
    try:
        return "~/" + str(path.resolve().relative_to(home.resolve()))
    except (OSError, ValueError):
        return str(path)


def _safe_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _is_newer(candidate: datetime | None, current: datetime | None) -> bool:
    if current is None:
        return True
    if candidate is None:
        return False
    return candidate > current


def _int_or_none(raw: object) -> int | None:
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        return int(raw)
    if isinstance(raw, str) and raw.strip().isdigit():
        return int(raw.strip())
    return None


def _float_or_none(raw: object) -> float | None:
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int | float):
        return float(raw)
    if isinstance(raw, str):
        try:
            return float(raw.strip())
        except ValueError:
            return None
    return None


def _string_or_none(raw: object) -> str | None:
    if not isinstance(raw, str):
        return None
    value = raw.strip()
    return value or None


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
    return []


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
    return []


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
    ]
