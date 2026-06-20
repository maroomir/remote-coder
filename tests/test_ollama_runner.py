import json
from pathlib import Path
from unittest.mock import Mock, patch

import httpx

from app.ai.base import RunnerInput
from app.ai.ollama import OllamaRunner, list_ollama_model_names
from app.jobs.schemas import JobMode


def _mock_transport(handler):
    return httpx.MockTransport(handler)


def test_list_ollama_model_names_reads_local_tags():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/tags"
        return httpx.Response(
            200,
            json={
                "models": [
                    {"name": "llama3.2:latest"},
                    {"model": "qwen2.5-coder:7b"},
                ]
            },
        )

    with patch("app.ai.ollama.httpx.Client", return_value=httpx.Client(transport=_mock_transport(handler))):
        assert list_ollama_model_names() == ("llama3.2:latest", "qwen2.5-coder:7b")


def test_ollama_runner_posts_chat_and_formats_usage(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("REMOTE_CODER_HOME", str(tmp_path / "home"))

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/chat"
        payload = json.loads(request.content.decode("utf-8"))
        assert payload["model"] == "llama3.2:latest"
        assert payload["stream"] is False
        assert payload["messages"][-1]["role"] == "user"
        return httpx.Response(
            200,
            json={
                "model": "llama3.2:latest",
                "message": {"role": "assistant", "content": "done"},
                "prompt_eval_count": 10,
                "eval_count": 5,
            },
        )

    chunks: list[tuple[str, str]] = []
    with patch("app.ai.ollama.httpx.Client", return_value=httpx.Client(transport=_mock_transport(handler))):
        result = OllamaRunner().run(
            RunnerInput(
                instruction="test",
                cwd=tmp_path,
                timeout_seconds=10,
                model_id="llama3.2:latest",
                session_id="11111111-1111-1111-1111-111111111111",
                output_callback=lambda stream, chunk: chunks.append((stream, chunk)),
            )
        )

    assert result.exit_code == 0
    assert result.session_id == "11111111-1111-1111-1111-111111111111"
    assert "done" in result.stdout
    assert "model: llama3.2:latest" in result.stdout
    assert "input tokens: 10" in result.stdout
    assert "output tokens: 5" in result.stdout
    assert chunks and chunks[0][0] == "stdout"


def test_ollama_runner_loads_session_history(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    session_dir = home / "ollama_sessions"
    session_dir.mkdir(parents=True)
    session = session_dir / "22222222-2222-2222-2222-222222222222.jsonl"
    session.write_text(
        json.dumps({"role": "user", "content": "first"}) + "\n"
        + json.dumps({"role": "assistant", "content": "answer"}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("REMOTE_CODER_HOME", str(home))

    captured_messages = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        captured_messages.extend(payload["messages"])
        return httpx.Response(
            200,
            json={"model": "llama3.2", "message": {"role": "assistant", "content": "next"}},
        )

    with patch("app.ai.ollama.httpx.Client", return_value=httpx.Client(transport=_mock_transport(handler))):
        result = OllamaRunner().run(
            RunnerInput(
                instruction="follow up",
                cwd=tmp_path,
                timeout_seconds=10,
                model_id="llama3.2",
                resume_token="22222222-2222-2222-2222-222222222222",
            )
        )

    assert result.session_id == "22222222-2222-2222-2222-222222222222"
    assert captured_messages[0] == {"role": "user", "content": "first"}
    assert captured_messages[1] == {"role": "assistant", "content": "answer"}
    assert captured_messages[-1]["role"] == "user"
    assert "follow up" in captured_messages[-1]["content"]


def test_ollama_runner_applies_diff_blocks_in_agent_mode(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("REMOTE_CODER_HOME", str(tmp_path / "home"))
    diff = """```diff
diff --git a/README.md b/README.md
--- a/README.md
+++ b/README.md
@@ -1 +1 @@
-old
+new
```"""

    def handler(request: httpx.Request) -> httpx.Response:
        _ = request
        return httpx.Response(
            200,
            json={"model": "llama3.2", "message": {"role": "assistant", "content": diff}},
        )

    with (
        patch("app.ai.ollama.httpx.Client", return_value=httpx.Client(transport=_mock_transport(handler))),
        patch("app.ai.ollama.subprocess.run", return_value=Mock(returncode=0, stdout="", stderr="")) as mock_run,
    ):
        result = OllamaRunner().run(
            RunnerInput(
                instruction="change readme",
                cwd=tmp_path,
                timeout_seconds=10,
                model_id="llama3.2",
                mode=JobMode.AGENT,
            )
        )

    assert result.exit_code == 0
    assert "applied patches: 1" in result.stdout
    assert mock_run.call_args.args[0] == ["git", "apply", "--whitespace=nowarn"]


def test_ollama_runner_does_not_apply_patches_in_plan_mode(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("REMOTE_CODER_HOME", str(tmp_path / "home"))

    def handler(request: httpx.Request) -> httpx.Response:
        _ = request
        return httpx.Response(
            200,
            json={
                "model": "llama3.2",
                "message": {"role": "assistant", "content": "```diff\npatch\n```"},
            },
        )

    with (
        patch("app.ai.ollama.httpx.Client", return_value=httpx.Client(transport=_mock_transport(handler))),
        patch("app.ai.ollama.subprocess.run") as mock_run,
    ):
        result = OllamaRunner().run(
            RunnerInput(
                instruction="plan only",
                cwd=tmp_path,
                timeout_seconds=10,
                model_id="llama3.2",
                mode=JobMode.PLAN,
            )
        )

    assert result.exit_code == 0
    mock_run.assert_not_called()
