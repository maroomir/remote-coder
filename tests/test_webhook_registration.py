import json

import respx
from httpx import Response
from pydantic import SecretStr

from app.models import ModelName
from app.projects.registry import ProjectRecord, build_public_webhook_url
from app.telegram.webhook_registration import TelegramWebhookRegistrar


@respx.mock
def test_webhook_registrar_sets_project_webhook(tmp_path):
    token = "123456:ABC-webhook-reg"
    public_base_url = "https://abcd.ngrok-free.app/"
    route = respx.post(f"https://api.telegram.org/bot{token}/setWebhook").mock(
        return_value=Response(200, json={"ok": True, "description": "Webhook was set"})
    )
    record = ProjectRecord(
        name="whproj",
        root_path=tmp_path,
        worktree_base_dir=tmp_path / "wt",
        default_model=ModelName.CLAUDE,
        enabled=True,
        bot_token=SecretStr(token),
        webhook_secret=SecretStr("wh-secret"),
        allowed_chat_ids=[123],
        allowed_user_ids=[],
    )

    assert TelegramWebhookRegistrar(public_base_url).sync_project(record) is True

    assert route.called
    payload = json.loads(route.calls[0].request.content)
    assert payload == {
        "url": build_public_webhook_url(public_base_url, token),
        "drop_pending_updates": True,
        "secret_token": "wh-secret",
    }


@respx.mock
def test_webhook_registrar_sets_bot_commands(tmp_path):
    token = "123456:ABC-command-reg"
    public_base_url = "https://abcd.ngrok-free.app/"
    respx.post(f"https://api.telegram.org/bot{token}/setWebhook").mock(
        return_value=Response(200, json={"ok": True})
    )
    commands_route = respx.post(f"https://api.telegram.org/bot{token}/setMyCommands").mock(
        return_value=Response(200, json={"ok": True})
    )
    record = ProjectRecord(
        name="cmdproj",
        root_path=tmp_path,
        worktree_base_dir=tmp_path / "wt",
        default_model=ModelName.CLAUDE,
        enabled=True,
        bot_token=SecretStr(token),
        allowed_chat_ids=[123],
        allowed_user_ids=[],
    )
    bot_commands = [{"command": "help", "description": "사용 가능한 명령어를 확인합니다"}]

    assert TelegramWebhookRegistrar(public_base_url, bot_commands=bot_commands).sync_project(record) is True

    assert commands_route.called
    payload = json.loads(commands_route.calls[0].request.content)
    assert payload == {"commands": bot_commands}


@respx.mock
def test_webhook_registrar_skips_disabled_project(tmp_path):
    token = "123456:ABC-webhook-disabled"
    record = ProjectRecord(
        name="disabled",
        root_path=tmp_path,
        worktree_base_dir=tmp_path / "wt",
        default_model=ModelName.CLAUDE,
        enabled=False,
        bot_token=SecretStr(token),
        allowed_chat_ids=[123],
        allowed_user_ids=[],
    )

    assert TelegramWebhookRegistrar("https://abcd.ngrok-free.app").sync_project(record) is False
    assert len(respx.calls) == 0
