from __future__ import annotations

import httpx

from app.monitoring.events import EventLogger
from app.projects.registry import ProjectRecord, build_public_webhook_url

_webhooklog = EventLogger("app.telegram.webhook_registration", "telegram.webhook")


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
        if self._bot_commands and not self._sync_bot_commands(record.name, token):
            return False
        return True

    def _sync_bot_commands(self, project_name: str, token: str) -> bool:
        api_url = f"https://api.telegram.org/bot{token}/setMyCommands"
        try:
            response = httpx.post(
                api_url,
                json={"commands": self._bot_commands},
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
