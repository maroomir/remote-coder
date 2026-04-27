from app.config import Settings
from app.models import ModelName


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
