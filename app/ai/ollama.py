from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from app.ai.base import AiRunner, RunnerInput, RunnerResult, instruction_for_runner_mode
from app.config import remote_coder_home
from app.jobs.schemas import is_read_only_job_mode
from app.monitoring.events import EventLogger

_log = EventLogger("app.ai.ollama", "ai.runner")

_DEFAULT_OLLAMA_HOST = "http://127.0.0.1:11434"
_MODEL_LIST_TIMEOUT_SEC = 2.0
_SESSION_HISTORY_LIMIT = 24
_SESSION_HISTORY_CHAR_LIMIT = 80_000
_PATCH_BLOCK_RE = re.compile(r"```(?:diff|patch)\s*\n(.*?)```", re.IGNORECASE | re.DOTALL)


@dataclass(frozen=True)
class OllamaChatResponse:
    content: str
    model: str
    token_usage: dict[str, int]


def ollama_base_url(env: dict[str, str] | None = None) -> str:
    raw = ""
    if env is not None:
        raw = env.get("OLLAMA_HOST", "").strip()
    raw = raw or os.environ.get("OLLAMA_HOST", "").strip() or _DEFAULT_OLLAMA_HOST
    if "://" not in raw:
        raw = f"http://{raw}"
    return raw.rstrip("/")


def list_ollama_model_names(
    timeout_seconds: float = _MODEL_LIST_TIMEOUT_SEC,
    *,
    env: dict[str, str] | None = None,
) -> tuple[str, ...]:
    try:
        with httpx.Client(timeout=timeout_seconds) as client:
            response = client.get(f"{ollama_base_url(env)}/api/tags")
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, json.JSONDecodeError, OSError, ValueError):
        return ()

    raw_models = data.get("models") if isinstance(data, dict) else None
    if not isinstance(raw_models, list):
        return ()

    names: list[str] = []
    for item in raw_models:
        if not isinstance(item, dict):
            continue
        raw_name = item.get("name") or item.get("model")
        if not isinstance(raw_name, str):
            continue
        name = raw_name.strip()
        if name:
            names.append(name)
    return tuple(sorted(dict.fromkeys(names), key=str.lower))


def default_ollama_model_name(env: dict[str, str] | None = None) -> str | None:
    configured = ""
    if env is not None:
        configured = env.get("REMOTE_CODER_OLLAMA_DEFAULT_MODEL", "").strip()
    configured = configured or os.environ.get("REMOTE_CODER_OLLAMA_DEFAULT_MODEL", "").strip()
    if configured:
        return configured
    models = list_ollama_model_names(env=env)
    return models[0] if models else None


def ollama_session_dir() -> Path:
    return (remote_coder_home() / "ollama_sessions").resolve()


def _session_path(session_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.:-]", "_", session_id)[:128]
    return ollama_session_dir() / f"{safe}.jsonl"


def _load_session_messages(session_id: str) -> list[dict[str, str]]:
    path = _session_path(session_id)
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []

    messages: list[dict[str, str]] = []
    total_chars = 0
    for line in reversed(lines):
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        role = item.get("role")
        content = item.get("content")
        if role not in {"user", "assistant", "system"} or not isinstance(content, str):
            continue
        total_chars += len(content)
        if total_chars > _SESSION_HISTORY_CHAR_LIMIT:
            break
        messages.append({"role": role, "content": content})
        if len(messages) >= _SESSION_HISTORY_LIMIT:
            break
    messages.reverse()
    return messages


def _append_session_message(
    session_id: str,
    *,
    role: str,
    content: str,
    model: str | None = None,
    token_usage: dict[str, int] | None = None,
) -> None:
    directory = ollama_session_dir()
    directory.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "timestamp": datetime.now(UTC).isoformat(),
        "role": role,
        "content": content,
    }
    if model:
        payload["model"] = model
    if token_usage:
        payload["token_usage"] = token_usage
    with _session_path(session_id).open("a", encoding="utf-8") as file:
        file.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _token_usage_from_response(data: dict[str, Any]) -> dict[str, int]:
    prompt = _int_or_none(data.get("prompt_eval_count"))
    output = _int_or_none(data.get("eval_count"))
    usage: dict[str, int] = {}
    if prompt is not None:
        usage["input"] = prompt
    if output is not None:
        usage["output"] = output
    if usage:
        usage["total"] = sum(usage.values())
    return usage


def _int_or_none(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def _format_stdout(response: OllamaChatResponse, *, patch_count: int = 0) -> str:
    parts = [response.content.strip()]
    metadata = [f"model: {response.model}"]
    if response.token_usage:
        if "input" in response.token_usage:
            metadata.append(f"input tokens: {response.token_usage['input']}")
        if "output" in response.token_usage:
            metadata.append(f"output tokens: {response.token_usage['output']}")
        if "total" in response.token_usage:
            metadata.append(f"total tokens: {response.token_usage['total']}")
    if patch_count:
        metadata.append(f"applied patches: {patch_count}")
    parts.append("[remote-coder ollama]\n" + "\n".join(metadata))
    return "\n\n".join(part for part in parts if part)


def _prompt_for_ollama(runner_input: RunnerInput) -> str:
    prompt = instruction_for_runner_mode(runner_input.instruction, runner_input.mode)
    if is_read_only_job_mode(runner_input.mode):
        return prompt
    return (
        "You are running as the Ollama local-model adapter inside a Git worktree. "
        "When code changes are needed, output unified diff patches in fenced ```diff blocks. "
        "The runner will apply valid patch blocks with git apply. If you cannot make a safe "
        "change from the available context, explain what file context is missing instead of "
        "guessing.\n\n"
        f"User request:\n{prompt}"
    )


def _extract_patch_blocks(text: str) -> list[str]:
    patches: list[str] = []
    for match in _PATCH_BLOCK_RE.finditer(text):
        patch = match.group(1).strip()
        if patch:
            patches.append(patch + "\n")
    return patches


class OllamaRunner(AiRunner):
    name = "ollama"

    def run(self, runner_input: RunnerInput) -> RunnerResult:
        started_at = datetime.now(UTC)
        model = runner_input.model_id or default_ollama_model_name(runner_input.env)
        if model is None:
            return RunnerResult(
                exit_code=1,
                stdout="",
                stderr=(
                    "No local Ollama model is available. Start Ollama and run "
                    "`ollama pull <model>`, then select it with `/model ollama <model>`."
                ),
                started_at=started_at,
                finished_at=datetime.now(UTC),
                session_id=self._result_session_id(runner_input),
            )

        session_id = self._result_session_id(runner_input)
        prompt = _prompt_for_ollama(runner_input)
        messages = _load_session_messages(session_id) if session_id else []
        messages.append({"role": "user", "content": prompt})

        _log.info(
            "start cwd=%s timeout=%d model_id=%s session=%s instruction_len=%d",
            runner_input.cwd.name,
            runner_input.timeout_seconds,
            model,
            "yes" if session_id else "no",
            len(runner_input.instruction),
        )
        if runner_input.cancel_event is not None and runner_input.cancel_event.is_set():
            return RunnerResult(
                exit_code=1,
                stdout="",
                stderr="The job was cancelled.",
                started_at=started_at,
                finished_at=datetime.now(UTC),
                session_id=session_id,
            )

        try:
            response = self._chat(model, messages, runner_input)
        except RuntimeError as exc:
            return RunnerResult(
                exit_code=1,
                stdout="",
                stderr=str(exc),
                started_at=started_at,
                finished_at=datetime.now(UTC),
                session_id=session_id,
            )
        if response is None:
            return RunnerResult(
                exit_code=1,
                stdout="",
                stderr="Ollama returned an empty response.",
                started_at=started_at,
                finished_at=datetime.now(UTC),
                session_id=session_id,
            )

        patch_count = 0
        stderr = ""
        if not is_read_only_job_mode(runner_input.mode):
            patch_result = self._apply_patch_blocks(response.content, runner_input)
            if patch_result.returncode != 0:
                stderr = patch_result.stderr.strip() or patch_result.stdout.strip()
                return RunnerResult(
                    exit_code=patch_result.returncode,
                    stdout=_format_stdout(response),
                    stderr=stderr,
                    started_at=started_at,
                    finished_at=datetime.now(UTC),
                    session_id=session_id,
                )
            patch_count = patch_result.patch_count

        stdout = _format_stdout(response, patch_count=patch_count)
        if runner_input.output_callback is not None and stdout:
            runner_input.output_callback("stdout", stdout + "\n")
        if session_id:
            _append_session_message(session_id, role="user", content=prompt, model=model)
            _append_session_message(
                session_id,
                role="assistant",
                content=response.content,
                model=response.model,
                token_usage=response.token_usage,
            )
        _log.info(
            "done model=%s stdout_len=%d patch_count=%d",
            response.model,
            len(stdout),
            patch_count,
        )
        return RunnerResult(
            exit_code=0,
            stdout=stdout,
            stderr=stderr,
            started_at=started_at,
            finished_at=datetime.now(UTC),
            session_id=session_id,
        )

    @staticmethod
    def _result_session_id(runner_input: RunnerInput) -> str | None:
        return runner_input.resume_token or runner_input.session_id

    def _chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        runner_input: RunnerInput,
    ) -> OllamaChatResponse | None:
        body = {"model": model, "messages": messages, "stream": False}
        try:
            with httpx.Client(timeout=runner_input.timeout_seconds) as client:
                response = client.post(f"{ollama_base_url(runner_input.env)}/api/chat", json=body)
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException:
            raise RuntimeError(
                f"Ollama chat timed out after {runner_input.timeout_seconds}s"
            ) from None
        except (httpx.HTTPError, json.JSONDecodeError, ValueError) as exc:
            _log.warning("ollama chat failed model=%s: %s", model, exc)
            raise RuntimeError(f"Ollama chat failed: {exc}") from exc

        message = data.get("message") if isinstance(data, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            return None
        actual_model = data.get("model") if isinstance(data.get("model"), str) else model
        return OllamaChatResponse(
            content=content,
            model=actual_model,
            token_usage=_token_usage_from_response(data),
        )

    def _apply_patch_blocks(self, text: str, runner_input: RunnerInput) -> _PatchApplyResult:
        patches = _extract_patch_blocks(text)
        if not patches:
            return _PatchApplyResult(returncode=0, patch_count=0, stdout="", stderr="")
        stdout_parts: list[str] = []
        stderr_parts: list[str] = []
        for patch in patches:
            try:
                proc = subprocess.run(
                    ["git", "apply", "--whitespace=nowarn"],
                    cwd=runner_input.cwd,
                    input=patch,
                    capture_output=True,
                    text=True,
                    timeout=min(60, max(1, runner_input.timeout_seconds)),
                    check=False,
                    shell=False,
                )
            except subprocess.TimeoutExpired:
                return _PatchApplyResult(
                    returncode=1,
                    patch_count=0,
                    stdout="".join(stdout_parts),
                    stderr="git apply timed out while applying an Ollama patch",
                )
            stdout_parts.append(proc.stdout or "")
            stderr_parts.append(proc.stderr or "")
            if proc.returncode != 0:
                return _PatchApplyResult(
                    returncode=proc.returncode,
                    patch_count=0,
                    stdout="".join(stdout_parts),
                    stderr="".join(stderr_parts),
                )
        return _PatchApplyResult(
            returncode=0,
            patch_count=len(patches),
            stdout="".join(stdout_parts),
            stderr="".join(stderr_parts),
        )


@dataclass(frozen=True)
class _PatchApplyResult:
    returncode: int
    patch_count: int
    stdout: str
    stderr: str
