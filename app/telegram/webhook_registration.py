from __future__ import annotations

from typing import TYPE_CHECKING

import httpx

from app.monitoring.events import EventLogger
from app.projects.registry import ProjectRecord, build_public_webhook_url

if TYPE_CHECKING:
    from app.config import Settings

_webhooklog = EventLogger("app.telegram.webhook_registration", "telegram.webhook")


def build_bot_command_payloads(
    commands: list[dict[str, str]],
    chat_ids: list[int] | None = None,
) -> list[dict[str, object]]:
    if not commands:
        return []

    payloads: list[dict[str, object]] = [
        {"commands": commands},
        {
            "commands": commands,
            "scope": {"type": "all_private_chats"},
        },
    ]
    for chat_id in dict.fromkeys(chat_ids or []):
        payloads.append(
            {
                "commands": commands,
                "scope": {"type": "chat", "chat_id": chat_id},
            }
        )
    return payloads


class TelegramWebhookRegistrar:
    def __init__(
        self,
        public_base_url: str,
        timeout_seconds: float = 10.0,
        bot_commands: list[dict[str, str]] | None = None,
    ) -> None:
        self._public_base_url = public_base_url.strip().rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._bot_commands = bot_commands or []

    def set_bot_commands(self, bot_commands: list[dict[str, str]]) -> None:
        self._bot_commands = bot_commands

    def sync_project_commands(self, record: ProjectRecord) -> bool:
        if not record.enabled or not self._bot_commands:
            return False
        token = record.bot_token.get_secret_value().strip()
        return self._sync_bot_commands(record.name, token, record.allowed_chat_ids)

    def sync_project(self, record: ProjectRecord) -> bool:
        if not record.enabled:
            return False

        token = record.bot_token.get_secret_value().strip()
        webhook_url = build_public_webhook_url(self._public_base_url, token)
        payload: dict[str, object] = {
            "url": webhook_url,
            "drop_pending_updates": True,
        }
        secret = (
            record.webhook_secret.get_secret_value().strip()
            if record.webhook_secret
            else ""
        )
        if secret:
            payload["secret_token"] = secret

        api_url = f"https://api.telegram.org/bot{token}/setWebhook"
        try:
            response = httpx.post(api_url, json=payload, timeout=self._timeout_seconds)
            response.raise_for_status()
            result = response.json()
        except Exception as exc:
            _webhooklog.warning(
                "setWebhook request failed project=%s err=%s",
                record.name,
                exc,
                project=record.name,
            )
            return False

        if not result.get("ok"):
            _webhooklog.warning(
                "setWebhook rejected project=%s response=%s",
                record.name,
                result,
                project=record.name,
            )
            return False

        _webhooklog.info("setWebhook synced project=%s", record.name, project=record.name)
        if self._bot_commands and not self._sync_bot_commands(record.name, token, record.allowed_chat_ids):
            return False
        return True

    def _sync_bot_commands(self, project_name: str, token: str, chat_ids: list[int]) -> bool:
        api_url = f"https://api.telegram.org/bot{token}/setMyCommands"
        for payload in build_bot_command_payloads(self._bot_commands, chat_ids):
            try:
                response = httpx.post(
                    api_url,
                    json=payload,
                    timeout=self._timeout_seconds,
                )
                response.raise_for_status()
                result = response.json()
            except Exception as exc:
                _webhooklog.warning(
                    "setMyCommands request failed project=%s err=%s",
                    project_name,
                    exc,
                    project=project_name,
                )
                return False

            if not result.get("ok"):
                _webhooklog.warning(
                    "setMyCommands rejected project=%s response=%s",
                    project_name,
                    result,
                    project=project_name,
                )
                return False

        _webhooklog.info("setMyCommands synced project=%s", project_name, project=project_name)
        return True


def register_all_enabled_projects(public_base_url: str, settings: "Settings") -> bool:
    """Refresh Telegram webhook + command menu for every enabled registry project.

    Shared by `remote-coder up` and `scripts/set_webhook.py`. Returns True only
    when every enabled project synced successfully; missing/empty registry is a failure.
    """
    from app.projects.registry import ProjectRegistry, projects_config_path_for_settings
    from app.telegram.commands import default_telegram_bot_commands

    config_path = projects_config_path_for_settings(
        settings.project_root,
        settings.projects_config_path,
    )
    registry = ProjectRegistry(config_path)
    registry.load()

    enabled = [record for record in registry.list_projects() if record.enabled]
    if not enabled:
        _webhooklog.warning("no enabled projects to register config_path=%s", config_path)
        return False

    registrar = TelegramWebhookRegistrar(
        public_base_url,
        bot_commands=default_telegram_bot_commands(),
    )
    all_succeeded = True
    for record in enabled:
        if not record.bot_token.get_secret_value().strip():
            _webhooklog.warning("empty bot_token project=%s", record.name, project=record.name)
            all_succeeded = False
            continue
        if not registrar.sync_project(record):
            all_succeeded = False
    return all_succeeded
