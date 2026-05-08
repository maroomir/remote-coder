from app.config import Settings
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
