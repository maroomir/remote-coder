# Multi-Bot And Multi-Project Setup

*English: this document · 한국어: [multi-bot-setup.ko.md](multi-bot-setup.ko.md)*

Remote Coder uses **one Telegram bot per registered project**. There is no `/project` command in chat. The bot you talk to determines which Git repository receives the request.

## Prerequisites

- Telegram must be able to call a public HTTPS base URL, such as an ngrok URL.
- Project metadata, bot tokens, and allowlists are stored in `~/.remote-coder/projects.json`.
- Global behavior settings are stored in `~/.remote-coder/advanced_settings.json`.

## Security Notes

- `projects.json` stores **BotFather tokens in plain text**. Restrict file permissions and never commit it.
- Keep the admin UI and `/api/*` on localhost. A leaked token can let someone take over the bot.
- Admin API responses mask token values.

## 1. Create Bots In BotFather

1. Open [@BotFather](https://t.me/BotFather) in Telegram.
2. Create a bot with `/newbot` and copy its **HTTP API token**.
3. Optional: prepare a long random `secret_token` for webhook verification. Store it as `webhook_secret` in the project record and pass the same value when registering the Telegram webhook.

Create **one bot per project** if you manage more than one repository.

## 2. Register A Project In The Admin UI

### Easy setup (recommended)

1. Start the server and open `http://127.0.0.1:8000/` on the same machine. When no project is registered yet, the dashboard shows the **Easy setup** wizard automatically (or click **Easy setup** at the top right).
2. Paste the **bot token** and click **Verify token**. The server validates it against Telegram (`getMe`).
3. Open a chat with your new bot in Telegram and send it any message — the wizard detects the **chat ID** automatically (`getUpdates`). You can also type it in manually.
4. Enter the **project name**, **repository root path**, and **default model**, then click **Create project**. The bot goes live without a restart.

> Auto chat detection reads `getUpdates`, which Telegram disables while a webhook is set. During first-time setup the webhook is not registered yet, so detection works; if it fails (e.g. a webhook is already active), enter the chat ID manually.

### Full form

For multiple Chat IDs, allowed User IDs, or a webhook secret, use the **Projects** page (`http://127.0.0.1:8000/projects`):

1. Enter the **project name**, **repository root path**, and **default model**.
2. Enter the bot's **bot_token**, optional **webhook_secret**, at least one **allowed Chat ID**, and optional **allowed User IDs**. When creating a project, leaving the secret blank makes the admin API generate a unique 256-bit URL-safe value automatically.
3. Save the project. The server registers the bot instance without a restart.

Worktrees are created automatically under `~/.remote-coder/worktrees/<project>/`.

`GET /api/projects` includes each bot's **`webhook_path`** such as `/telegram/webhook/<16-hex-prefix>` and **`token_hash_prefix`**. The full webhook URL is `<public HTTPS base>` + `webhook_path`.

### Webhook URL And Token Hash

The final path segment is the first **16 hex characters** of the bot token's SHA-256 digest. If you regenerate the token in BotFather, the prefix changes and the webhook URL must be registered again.

## 3. Register Webhooks

Pass a public base URL to register `setWebhook` for every **enabled** project. `remote-coder up` normally does this automatically with the ngrok URL. Use this command only when you need to register a fixed external URL manually.

```bash
python scripts/set_webhook.py https://your-host.example
# If developing from the repository with Conda, activate remote-coder first.
```

If a project has `webhook_secret`, it is registered with Telegram as `secret_token`.

### Cleanup After Deleting Or Disabling A Project

When you **delete** or **disable** a project, the server stops matching webhook paths for that token hash prefix. Telegram may still keep the old webhook URL. To fully disconnect or repoint a bot, call `deleteWebhook` for that bot or rerun `scripts/set_webhook.py` against the current registry.

## 4. Use The Bot In Chat

- Use `/start` or a natural-language request in a 1:1 chat or group with an allowed Chat/User.
- Natural-language options support only `model:`, `branch:`, and `no commit`. There is **no `project:` token**.
- `/init` resets only this chat's **default-model override** and **pending confirmation state**. It does not change the project bound to the bot.

## Migration From `.env`

`.env`-based seeding has been removed.

1. Run `remote-coder up`, then register each project's `bot_token`, allowlist, and `root_path` from the admin UI first-time setup card or `/projects`.
2. Move global options such as `GIT_REMOTE_NAME`, `CODEX_SANDBOX`, and `JOB_TIMEOUT_SECONDS` to `/advanced` or `advanced_settings.json`.
3. Delete old `.env` files or remove sensitive values from them.

For the compact setup overview, see [README.md](../README.md).

## Future Improvement

Replacing plain-text token storage with OS keychain or encrypted storage can be considered separately. The current MVP uses a file-based registry.
