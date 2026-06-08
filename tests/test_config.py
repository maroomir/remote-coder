from pathlib import Path

from app.config import Settings, remote_coder_home, worktrees_root


def test_remote_coder_home_defaults_to_dot_dir(monkeypatch):
    monkeypatch.delenv("REMOTE_CODER_HOME", raising=False)
    assert remote_coder_home() == Path.home() / ".remote-coder"


def test_remote_coder_home_honors_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("REMOTE_CODER_HOME", str(tmp_path))
    assert remote_coder_home() == tmp_path


def test_settings_paths_default_to_home(monkeypatch, tmp_path):
    monkeypatch.setenv("REMOTE_CODER_HOME", str(tmp_path))

    settings = Settings()

    assert worktrees_root() == (tmp_path / "worktrees").resolve()
    assert settings.job_db_path == (tmp_path / "jobs.sqlite3").resolve()
    assert settings.conversation_db_path == (tmp_path / "conversations.sqlite3").resolve()


def test_settings_normalize_webhook_public_base_url():
    settings = Settings(telegram_webhook_public_base_url="https://example.com/")
    assert settings.telegram_webhook_public_base_url == "https://example.com"
