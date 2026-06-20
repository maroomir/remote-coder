"""Characterization tests for app.ai.ollama edge cases.

Tester 3 (AI Runners & Git Automation). These lock in correct-but-undertested
behavior for F5-2: default-model selection, no-model error classification,
OLLAMA_HOST normalization, transcript truncation order, and the best-effort
patch-apply failure path.

No bug found in these paths; all assertions reflect current correct behavior.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import Mock, patch

import httpx

from app.ai.base import RunnerInput
from app.ai.ollama import (
    OllamaRunner,
    _load_session_messages,
    default_ollama_model_name,
    ollama_base_url,
    ollama_session_dir,
)
from app.jobs.schemas import JobMode


def _transport(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_ollama_base_url_normalizes_host_and_scheme():
    assert ollama_base_url() == "http://127.0.0.1:11434"
    assert ollama_base_url({"OLLAMA_HOST": "myhost:1234"}) == "http://myhost:1234"
    assert ollama_base_url({"OLLAMA_HOST": "https://h:9/"}) == "https://h:9"


def test_default_ollama_model_prefers_env_over_api():
    # Env override must win without touching the local daemon.
    with patch("app.ai.ollama.list_ollama_model_names") as mock_list:
        result = default_ollama_model_name({"REMOTE_CODER_OLLAMA_DEFAULT_MODEL": "qwen2.5:7b"})
    assert result == "qwen2.5:7b"
    mock_list.assert_not_called()


def test_default_ollama_model_falls_back_to_first_local_model():
    with patch("app.ai.ollama.list_ollama_model_names", return_value=("a:1", "b:2")):
        assert default_ollama_model_name(env={}) == "a:1"


def test_ollama_runner_reports_actionable_error_when_no_model(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("REMOTE_CODER_HOME", str(tmp_path / "home"))
    with patch("app.ai.ollama.list_ollama_model_names", return_value=()):
        result = OllamaRunner().run(
            RunnerInput(
                instruction="x",
                cwd=tmp_path,
                timeout_seconds=5,
                session_id="11111111-1111-1111-1111-111111111111",
            )
        )

    assert result.exit_code == 1
    assert "No local Ollama model is available" in result.stderr
    assert "ollama pull" in result.stderr
    # Logical session id is preserved for display even on failure.
    assert result.session_id == "11111111-1111-1111-1111-111111111111"


def test_ollama_runner_failed_patch_apply_classifies_as_runner_error(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("REMOTE_CODER_HOME", str(tmp_path / "home"))
    diff = (
        "```diff\n"
        "diff --git a/x b/x\n--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b\n"
        "```"
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"model": "m", "message": {"role": "assistant", "content": diff}},
        )

    with (
        patch("app.ai.ollama.httpx.Client", return_value=_transport(handler)),
        patch(
            "app.ai.ollama.subprocess.run",
            return_value=Mock(returncode=1, stdout="", stderr="error: patch does not apply"),
        ),
    ):
        result = OllamaRunner().run(
            RunnerInput(
                instruction="change x",
                cwd=tmp_path,
                timeout_seconds=10,
                model_id="m",
                mode=JobMode.AGENT,
            )
        )

    # A patch that cannot apply surfaces the git apply error with a non-zero exit,
    # so the job layer classifies and reports it instead of silently succeeding.
    assert result.exit_code != 0
    assert "patch does not apply" in result.stderr
    # The model's own output is still preserved for the failure summary.
    assert "model: m" in result.stdout


def test_ollama_runner_chat_timeout_is_classified(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("REMOTE_CODER_HOME", str(tmp_path / "home"))

    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("slow")

    with patch("app.ai.ollama.httpx.Client", return_value=_transport(handler)):
        result = OllamaRunner().run(
            RunnerInput(instruction="x", cwd=tmp_path, timeout_seconds=7, model_id="m")
        )

    assert result.exit_code == 1
    assert "timed out after 7s" in result.stderr


def _patch_response(diff_body: str):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"model": "m", "message": {"role": "assistant", "content": diff_body}},
        )

    return handler


def test_ollama_runner_refuses_patch_targeting_git_dir(tmp_path: Path, monkeypatch):
    # A `.git/hooks/` path is inside the worktree, so `git apply` would accept it;
    # the runner must refuse it before shelling out to git.
    monkeypatch.setenv("REMOTE_CODER_HOME", str(tmp_path / "home"))
    diff = (
        "```diff\n"
        "diff --git a/.git/hooks/post-commit b/.git/hooks/post-commit\n"
        "--- a/.git/hooks/post-commit\n+++ b/.git/hooks/post-commit\n"
        "@@ -0,0 +1 @@\n+evil\n"
        "```"
    )
    run_mock = Mock()
    with (
        patch("app.ai.ollama.httpx.Client", return_value=_transport(_patch_response(diff))),
        patch("app.ai.ollama.subprocess.run", run_mock),
    ):
        result = OllamaRunner().run(
            RunnerInput(instruction="x", cwd=tmp_path, timeout_seconds=10, model_id="m", mode=JobMode.AGENT)
        )

    assert result.exit_code != 0
    assert ".git/" in result.stderr
    run_mock.assert_not_called()


def test_ollama_runner_refuses_patch_with_parent_traversal(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("REMOTE_CODER_HOME", str(tmp_path / "home"))
    diff = (
        "```diff\n"
        "diff --git a/../../etc/evil b/../../etc/evil\n"
        "--- a/../../etc/evil\n+++ b/../../etc/evil\n"
        "@@ -0,0 +1 @@\n+evil\n"
        "```"
    )
    run_mock = Mock()
    with (
        patch("app.ai.ollama.httpx.Client", return_value=_transport(_patch_response(diff))),
        patch("app.ai.ollama.subprocess.run", run_mock),
    ):
        result = OllamaRunner().run(
            RunnerInput(instruction="x", cwd=tmp_path, timeout_seconds=10, model_id="m", mode=JobMode.AGENT)
        )

    assert result.exit_code != 0
    run_mock.assert_not_called()


def test_load_session_messages_keeps_recent_in_chronological_order(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("REMOTE_CODER_HOME", str(tmp_path / "home"))
    directory = ollama_session_dir()
    directory.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps({"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}"})
        for i in range(30)
    ]
    (directory / "sess.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

    messages = _load_session_messages("sess")

    assert len(messages) == 24
    assert messages[0]["content"] == "m6"
    assert messages[-1]["content"] == "m29"
    contents = [m["content"] for m in messages]
    assert contents == sorted(contents, key=lambda c: int(c[1:]))
