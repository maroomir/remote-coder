from __future__ import annotations

"""Register Telegram setWebhook/setMyCommands for each enabled project from one public HTTPS base URL.

Shares the same registration logic as `remote-coder up` (`register_all_enabled_projects`).
Disabled or deleted projects are skipped. Bots with stale URLs on Telegram can be cleared via
Bot API deleteWebhook or by re-running this script.
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python scripts/set_webhook.py <PUBLIC_HTTPS_URL>")
        print("Example: python scripts/set_webhook.py https://abcd-1234.ngrok-free.app")
        sys.exit(1)

    public_url = sys.argv[1].rstrip("/")
    if not public_url.startswith("https://"):
        print("Error: URL must start with https://")
        sys.exit(1)

    from app.config import get_settings
    from app.telegram.webhook_registration import register_all_enabled_projects

    settings = get_settings()
    print(f"Public URL: {public_url}")
    print("Registering Telegram webhooks and command menu for enabled projects...")
    if not register_all_enabled_projects(public_url, settings):
        print("❌ Some project registrations failed. (see server logs for details)")
        sys.exit(1)
    print("✅ Registration complete")


if __name__ == "__main__":
    main()
