from pathlib import Path

from app.config import Settings, remote_coder_home
from app.models import CodexSandboxMode, ModelName


def test_parse_allowed_chat_ids_from_string(tmp_path):
    settings = Settings(
        telegram_bot_token="token",
        telegram_allowed_chat_ids="1,2,3",
        telegram_allowed_user_ids="9,10",
        default_model="claude",
        default_project="proj",
        project_root=tmp_path,
        worktree_base_dir=tmp_path / "wt",
    )
    assert settings.telegram_allowed_chat_ids == [1, 2, 3]
    assert settings.telegram_allowed_user_ids == [9, 10]
    assert settings.default_model == ModelName.CLAUDE
    assert settings.git_remote_name == "origin"
    assert settings.codex_sandbox == CodexSandboxMode.WORKSPACE_WRITE
    assert settings.job_db_path == tmp_path / ".remote-coder" / "jobs.sqlite3"


def test_empty_telegram_seed_strings_normalize_to_none(tmp_path):
    settings = Settings(
        telegram_bot_token="   ",
        telegram_webhook_secret="",
        telegram_allowed_chat_ids=[1],
        telegram_allowed_user_ids=[],
        default_model="claude",
        default_project="proj",
        project_root=tmp_path,
        worktree_base_dir=tmp_path / "wt",
    )
    assert settings.telegram_bot_token is None
    assert settings.telegram_webhook_secret is None


def test_codex_sandbox_from_string(tmp_path):
    settings = Settings(
        telegram_bot_token="token",
        telegram_allowed_chat_ids=[1],
        telegram_allowed_user_ids=[],
        default_model="claude",
        default_project="proj",
        project_root=tmp_path,
        worktree_base_dir=tmp_path / "wt",
        codex_sandbox="read-only",
    )
    assert settings.codex_sandbox == CodexSandboxMode.READ_ONLY


def test_remote_coder_home_defaults_to_dot_dir(monkeypatch):
    monkeypatch.delenv("REMOTE_CODER_HOME", raising=False)
    assert remote_coder_home() == Path.home() / ".remote-coder"


def test_remote_coder_home_honors_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("REMOTE_CODER_HOME", str(tmp_path))
    assert remote_coder_home() == tmp_path


def test_settings_project_paths_default_to_home(monkeypatch, tmp_path):
    monkeypatch.setenv("REMOTE_CODER_HOME", str(tmp_path))
    monkeypatch.delenv("PROJECT_ROOT", raising=False)
    monkeypatch.delenv("WORKTREE_BASE_DIR", raising=False)

    settings = Settings(_env_file=None)

    assert settings.project_root == tmp_path
    assert settings.worktree_base_dir == tmp_path / "worktrees"
