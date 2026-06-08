import json

import respx
from httpx import Response
from pydantic import SecretStr

from app.config import Settings
from app.models import ModelName
from app.projects.registry import ProjectRecord, ProjectRegistry, build_public_webhook_url
from app.telegram.webhook_registration import (
    TelegramWebhookRegistrar,
    build_bot_command_payloads,
    register_all_enabled_projects,
)


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
        default_model=ModelName.CLAUDE,
        enabled=True,
        bot_token=SecretStr(token),
        allowed_chat_ids=[123],
        allowed_user_ids=[],
    )
    bot_commands = [{"command": "help", "description": "사용 가능한 명령어를 확인합니다"}]

    assert TelegramWebhookRegistrar(public_base_url, bot_commands=bot_commands).sync_project(record) is True

    assert commands_route.call_count == 3
    payloads = [json.loads(call.request.content) for call in commands_route.calls]
    assert payloads == [
        {"commands": bot_commands},
        {"commands": bot_commands, "scope": {"type": "all_private_chats"}},
        {"commands": bot_commands, "scope": {"type": "chat", "chat_id": 123}},
    ]


def test_build_bot_command_payloads_deduplicates_chat_scopes():
    bot_commands = [{"command": "help", "description": "사용 가능한 명령어를 확인합니다"}]

    assert build_bot_command_payloads(bot_commands, [123, 123, -456]) == [
        {"commands": bot_commands},
        {"commands": bot_commands, "scope": {"type": "all_private_chats"}},
        {"commands": bot_commands, "scope": {"type": "chat", "chat_id": 123}},
        {"commands": bot_commands, "scope": {"type": "chat", "chat_id": -456}},
    ]


@respx.mock
def test_webhook_registrar_skips_disabled_project(tmp_path):
    token = "123456:ABC-webhook-disabled"
    record = ProjectRecord(
        name="disabled",
        root_path=tmp_path,
        default_model=ModelName.CLAUDE,
        enabled=False,
        bot_token=SecretStr(token),
        allowed_chat_ids=[123],
        allowed_user_ids=[],
    )

    assert TelegramWebhookRegistrar("https://abcd.ngrok-free.app").sync_project(record) is False
    assert len(respx.calls) == 0


def _settings_with_registry(tmp_path) -> Settings:
    config_path = tmp_path / "projects.json"
    return Settings(projects_config_path=config_path)


@respx.mock
def test_register_all_enabled_projects_only_targets_enabled(tmp_path):
    public_url = "https://abcd.ngrok-free.app"
    enabled_token = "111:enabled-token"
    disabled_token = "222:disabled-token"

    settings = _settings_with_registry(tmp_path)
    registry = ProjectRegistry(settings.projects_config_path)
    registry.add_project(
        ProjectRecord(
            name="enabled-proj",
            root_path=tmp_path,
            default_model=ModelName.CLAUDE,
            enabled=True,
            bot_token=SecretStr(enabled_token),
            allowed_chat_ids=[123],
            allowed_user_ids=[],
        )
    )
    registry.add_project(
        ProjectRecord(
            name="disabled-proj",
            root_path=tmp_path,
            default_model=ModelName.CLAUDE,
            enabled=False,
            bot_token=SecretStr(disabled_token),
            allowed_chat_ids=[456],
            allowed_user_ids=[],
        )
    )

    webhook_route = respx.post(f"https://api.telegram.org/bot{enabled_token}/setWebhook").mock(
        return_value=Response(200, json={"ok": True})
    )
    respx.post(f"https://api.telegram.org/bot{enabled_token}/setMyCommands").mock(
        return_value=Response(200, json={"ok": True})
    )
    disabled_route = respx.post(f"https://api.telegram.org/bot{disabled_token}/setWebhook")

    assert register_all_enabled_projects(public_url, settings) is True
    assert webhook_route.called
    assert not disabled_route.called


def test_register_all_enabled_projects_returns_false_when_empty(tmp_path):
    settings = _settings_with_registry(tmp_path)

    assert register_all_enabled_projects("https://abcd.ngrok-free.app", settings) is False
