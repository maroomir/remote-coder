from subprocess import DEVNULL, CompletedProcess
from unittest.mock import patch

from app.git.ai_commit import AiCommitBodyGenerator
from app.models import ModelName


def _stub_run(stdout: str, returncode: int = 0, stderr: str = ""):
    def fake_run(argv, **kwargs):
        fake_run.last_argv = argv
        fake_run.last_kwargs = kwargs
        return CompletedProcess(args=argv, returncode=returncode, stdout=stdout, stderr=stderr)

    fake_run.last_argv = None
    fake_run.last_kwargs = None
    return fake_run


def test_ai_commit_generator_uses_claude_cli_for_claude_model():
    fake = _stub_run("title: refactor commit handling\n- AI cleaned commit handler\n- AI updated tests")
    generator = AiCommitBodyGenerator()
    with patch("app.git.ai_commit.subprocess.run", side_effect=fake):
        title, body = generator.generate(
            instruction="fix commit titles",
            changed_files=["app/git/commit_message.py"],
            model_name=ModelName.CLAUDE,
        )
    assert fake.last_argv[0] == "claude"
    assert "--dangerously-skip-permissions" in fake.last_argv
    assert title == "refactor commit handling"
    assert body == "- AI cleaned commit handler\n- AI updated tests"


def test_ai_commit_generator_uses_codex_cli_for_codex_model():
    fake = _stub_run("title: codex commit summary\n- Codex made a change")
    generator = AiCommitBodyGenerator()
    with patch("app.git.ai_commit.subprocess.run", side_effect=fake):
        title, body = generator.generate(
            instruction="apply codex fix",
            changed_files=["app/x.py"],
            model_name=ModelName.CODEX,
        )
    assert fake.last_argv[0] == "codex"
    assert fake.last_argv[1] == "exec"
    assert "--skip-git-repo-check" in fake.last_argv
    assert "--sandbox" in fake.last_argv
    assert "read-only" in fake.last_argv
    assert fake.last_kwargs["stdin"] is DEVNULL
    assert title == "codex commit summary"
    assert body == "- Codex made a change"


def test_ai_commit_generator_uses_gemini_cli_for_gemini_model():
    fake = _stub_run("title: gemini commit summary\n- Gemini wrote bullets")
    generator = AiCommitBodyGenerator()
    with patch("app.git.ai_commit.subprocess.run", side_effect=fake):
        title, body = generator.generate(
            instruction="apply gemini fix",
            changed_files=["app/y.py"],
            model_name=ModelName.GEMINI,
        )
    assert fake.last_argv[0] == "gemini"
    assert "-p" in fake.last_argv
    assert title == "gemini commit summary"
    assert body == "- Gemini wrote bullets"


def test_ai_commit_generator_uses_ollama_cli_for_ollama_model():
    fake = _stub_run("title: ollama commit summary\n- Ollama wrote bullets")
    generator = AiCommitBodyGenerator()
    with (
        patch("app.git.ai_commit.default_ollama_model_name", return_value="llama3.2:latest"),
        patch("app.git.ai_commit.subprocess.run", side_effect=fake),
    ):
        title, body = generator.generate(
            instruction="apply ollama fix",
            changed_files=["app/z.py"],
            model_name=ModelName.OLLAMA,
        )
    assert fake.last_argv[0:3] == ["ollama", "run", "llama3.2:latest"]
    assert "--nowordwrap" in fake.last_argv
    assert title == "ollama commit summary"
    assert body == "- Ollama wrote bullets"


def test_ai_commit_generator_returns_none_when_ollama_has_no_model():
    generator = AiCommitBodyGenerator()
    with patch("app.git.ai_commit.default_ollama_model_name", return_value=None):
        title, body = generator.generate(
            instruction="x",
            changed_files=[],
            model_name=ModelName.OLLAMA,
        )
    assert title is None
    assert body is None


def test_ai_commit_generator_returns_none_on_nonzero_exit():
    fake = _stub_run("noise", returncode=1)
    generator = AiCommitBodyGenerator()
    with patch("app.git.ai_commit.subprocess.run", side_effect=fake):
        title, body = generator.generate(
            instruction="x",
            changed_files=[],
            model_name=ModelName.CLAUDE,
        )
    assert title is None
    assert body is None


def test_ai_commit_generator_logs_stderr_preview_on_nonzero_exit(caplog):
    fake = _stub_run("", returncode=1, stderr="Not inside a trusted directory")
    generator = AiCommitBodyGenerator()
    with patch("app.git.ai_commit.subprocess.run", side_effect=fake), caplog.at_level(
        "WARNING",
        logger="app.git.ai_commit",
    ):
        title, body = generator.generate(
            instruction="x",
            changed_files=[],
            model_name=ModelName.CODEX,
        )
    assert title is None
    assert body is None
    assert "Not inside a trusted directory" in caplog.text


def test_ai_commit_generator_returns_none_when_cli_missing():
    def raise_not_found(*_args, **_kwargs):
        raise FileNotFoundError("no codex")

    generator = AiCommitBodyGenerator()
    with patch("app.git.ai_commit.subprocess.run", side_effect=raise_not_found):
        title, body = generator.generate(
            instruction="x",
            changed_files=[],
            model_name=ModelName.CODEX,
        )
    assert title is None
    assert body is None
