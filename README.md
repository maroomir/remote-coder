# Remote AI Coder

An MVP that runs AI coding tasks on your local development machine through Telegram messages and reports Git branch/commit results back as notifications.

> [!WARNING]
> This project runs AI CLI and Git operations on your local machine via Telegram messages. Do not expose the server or admin UI directly to the public internet. Always configure the Telegram allowlist (and optionally a webhook secret) and use it only in a private, trusted environment.

## Multi-bot model (summary)

- **Each registered project gets its own Telegram bot.** There is no `/project` command to switch the target repository from chat.
- Each bot has a distinct webhook path: `POST /telegram/webhook/{first 16 hex chars of SHA-256(bot token)}` (the token itself is never placed in the URL).
- Bot token, allowed Chat/User IDs, and an optional webhook secret are stored in the **project registry** (`projects.json`, etc.). **Tokens are stored in plain text**, so keep strict file permissions and a careful backup policy.
- See [`docs/multi-bot-setup.md`](docs/multi-bot-setup.md) for the full procedure.
- When a project is **disabled or deleted**, the server stops routing updates arriving with that token hash prefix. Even if an old URL remains registered on Telegram, this app ignores it. To clear or repoint a bot's webhook, call the Bot API `deleteWebhook` or re-run [`scripts/set_webhook.py`](scripts/set_webhook.py) against the current registry.

## Publishing / security notes

- Never commit `TELEGRAM_BOT_TOKEN` (optional seed), the registry `bot_token`, Chat/User IDs, webhook secrets, AI API keys, or personal paths to code or docs.
- `.env`, `.remote-coder/` (especially `projects.json`), worktrees, logs, and the SQLite conversation-memory file are local-only data. This repository's `.gitignore` excludes them by default.
- The admin UI (`/`, `/projects`, `/advanced`, `/logs`, `/database`) is designed for localhost only. Do not expose it externally via reverse proxy, ngrok, port forwarding, etc.
- Options such as Claude `--dangerously-skip-permissions`, Gemini `--approval-mode yolo`, and Codex `danger-full-access` can modify local files. Use them only after restricting the allowed projects and trusted users.
- The conversation-memory SQLite may store users' Telegram requests and Job summaries. Do not paste sensitive code into messages, and clean up with `/clear memory` or the admin UI advanced settings when needed.

See [`SECURITY.md`](SECURITY.md) for vulnerability reporting and pre-publication review steps.

## Prerequisites

- Python 3.11+ or Conda
- A Telegram Bot Token (BotFather) per project, plus allowed Chat IDs (required) and User IDs (optional)
- An HTTPS tunnel tool (e.g. ngrok for development)
- At least one of: Claude Code CLI, Codex CLI, Gemini CLI
- A target Git project and a local directory for worktrees

## Quick start (recommended)

Install with a single `pip` command — no separate Conda environment required. This installs the `remote-coder` CLI; check prerequisites (ngrok, AI CLIs) with `remote-coder doctor`.

```bash
pip install remote-coder
```

> Before the first PyPI release, install straight from the git source (this is still `pip`):
>
> ```bash
> pip install git+https://github.com/maroomir/remote-coder.git
> ```

After installing, start the server and finish setup in the browser:

```bash
remote-coder up     # ngrok tunnel + Telegram webhook registration + server, all at once (stop: Ctrl+C)
```

- On the first run (no projects yet), open the local admin UI at **http://127.0.0.1:8000/** and use the **First-time setup** card to add your first project (bot token, allowed Chat IDs, target repo path). The bot goes live as soon as the project is saved.
- The project registry (`projects.json` under `REMOTE_CODER_HOME`, default `~/.remote-coder`) is the source of truth; the admin UI writes to it. A global `REMOTE_CODER_HOME/.env` is optional and used only to seed the first project.
- Prerequisites: `ngrok` (after installing, run `ngrok config add-authtoken <token>`) and at least one AI CLI (`claude`/`codex`/`gemini`). Check them with `remote-coder doctor` or in the setup card.
- To run the server only, without a tunnel: `remote-coder up --no-tunnel`.

### Other installation methods

If you prefer isolated installs, use [pipx](https://pipx.pypa.io/) or [uv](https://docs.astral.sh/uv/). (Before the PyPI release, use `git+https://github.com/maroomir/remote-coder.git` instead of the package name.)

```bash
pipx install remote-coder
uv tool install remote-coder
```

There is also an install script that handles prerequisite checks in one go (isolated install via uv):

```bash
curl -fsSL https://raw.githubusercontent.com/maroomir/remote-coder/main/scripts/install.sh | bash
```

### Development install

Editable install from a source checkout:

```bash
python -m pip install -e ".[dev]"
remote-coder up --no-tunnel --reload
```

`remote-coder up --no-tunnel` runs the server only, without tunnel/webhook registration — equivalent to `uvicorn app.main:app`.

To do both steps in one go (ensure editable install, then run with reload), use `./scripts/dev.sh` (runs in the `remote-coder` conda env). For live testing with the tunnel, run `remote-coder up --reload` instead.

### Building distribution packages

```bash
python -m pip install build
python -m build
```

Outputs are `dist/remote_coder-<version>.tar.gz` and `dist/remote_coder-<version>-py3-none-any.whl`. Pushing a tag (`vX.Y.Z`) makes GitHub Actions build, publish to PyPI (Trusted Publishing), and create a GitHub Release automatically.

### Homebrew distribution

Since this is a CLI/server package, a Formula (`brew install remote-coder`) is a better fit than a macOS app-bundle Cask. A draft Formula is at [`packaging/homebrew/remote-coder.rb`](packaging/homebrew/remote-coder.rb).

After a release you still need to:

- Replace `homepage` with the actual repository URL
- Replace `url` with the `remote_coder-<version>.tar.gz` URL from PyPI or the GitHub Release
- Replace `sha256` with the value from `shasum -a 256 dist/remote_coder-<version>.tar.gz`
- Generate the Python dependency `resource` blocks with a tool like `brew pypi-poet remote-coder` and add them to the Formula

> Sections "1) – 3)" below are for **developers/contributors** who work directly from the repository or handle configuration manually instead of using `remote-coder up` plus the admin UI. Skip them if the quick start is enough.

## 1) Environment setup (Conda, for developers/contributors)

```bash
conda env create -f environment.yml
conda activate remote-coder
```

## 2) Configuration

Copy and edit this `.env` only when configuring manually instead of using the admin UI. The `.env` is optional and seeds the first project when the registry is empty. (When running globally, `REMOTE_CODER_HOME/.env` takes precedence; when developing inside the repo, the current directory's `.env` takes precedence.)

```bash
cp .env.example .env
```

Fill in the following values in `.env`:

- Optional (initial seed): `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_CHAT_IDS`, `TELEGRAM_ALLOWED_USER_IDS`, `TELEGRAM_WEBHOOK_SECRET` — used only to create the first project when the registry is empty. Production settings prefer the **per-project** fields in the admin UI or `projects.json`.
- Optional: `GIT_REMOTE_NAME` (default `origin`) — used for push after commit and for `/rebase`, `/pr`, `/clear`
- Optional: `PROJECTS_CONFIG_PATH` — path to the registry file (JSON or `.yaml`) for multiple Git projects
- Optional: `CONVERSATION_DB_PATH` — SQLite path for per-project + per-chat conversation memory (defaults to `~/.remote-coder/conversations.sqlite3`)
- Optional: `CONVERSATION_RECENT_LIMIT` — number of recent records appended to the runner for ambiguous follow-ups (default `10`)
- Optional: `CODEX_SANDBOX` — the Codex `codex exec --sandbox` value (`read-only`, `workspace-write`, `danger-full-access`). Default `workspace-write` (files can be edited in the Job worktree)
- Optional: to use Gemini, install the Gemini CLI with `npm install -g @google/gemini-cli` and make sure `gemini` is on your PATH
- Initial seed (one-time): `DEFAULT_PROJECT`, `PROJECT_ROOT`
- Worktrees are created automatically under `~/.remote-coder/worktrees/<project>/`; there is no worktree path to configure

If you were using a single `.env` before → move each project's `bot_token`/allowlist into the admin UI, or clean sensitive values from `.env` after the seed is created. See the migration section in [`docs/multi-bot-setup.md`](docs/multi-bot-setup.md).

## 2.5) Local admin UI (project registration)

After starting the server, open it in a browser **on the same machine**.

- Admin hub: `http://127.0.0.1:8000/` (summary, navigation to other pages)
- Project registration: `http://127.0.0.1:8000/projects` (list, add/edit/delete, fallback defaults, **bot token / allowlist / webhook secret**, per-bot webhook path. While `remote-coder up` is running, the Telegram webhook and `/` command menu for active projects you add/edit are refreshed immediately)
- Advanced settings: `http://127.0.0.1:8000/advanced`
- Server logs: `http://127.0.0.1:8000/logs` (in-memory ring buffer for the `app` logger; auto-refresh, category and `chat_id`/`job_id` filters)
- Data browser: `http://127.0.0.1:8000/database` (browse the conversation-memory SQLite tables, export CSV)
- The natural-language task target is **bound to its bot**. The `project:` token is not supported.
- If `PROJECTS_CONFIG_PATH` is unset, the default path `~/.remote-coder/projects.json` is used (an existing `PROJECT_ROOT/.remote-coder/projects.json` is still read for backward compatibility).
- If the registry file is missing, it is created automatically from the `.env` seed values (`DEFAULT_PROJECT`, `PROJECT_ROOT`).

### Server log (event) logger naming convention

Entries shown in the admin UI `/logs` and the API `GET /api/logs` are recorded by `app` package loggers. The main logger names and their purposes:

| Logger name | Purpose |
|-------------|---------|
| `app.telegram.inbound` | Webhook receipt, empty-message skips |
| `app.telegram.outbound` | `sendMessage` success/failure, Job intake/result notifications |
| `app.telegram.command` | Slash-command handling, natural-language Job intake, state changes like `/init`/`/clear` confirmations |
| `app.security.auth` | Webhook secret mismatch, allowlist rejection |
| `app.jobs.lifecycle` | Job submission, stages (`git_worktree`/`runner`/…), success, failure |
| `app.git.service` | Git adapter: worktree creation, commit, push, cleanup, rebase integration |
| `app.ai.claude` / `app.ai.codex` / `app.ai.gemini` | Runner start/end/timeout |

Structured fields (`category`, `chat_id`, `user_id`, `project`, `job_id`) can be filtered/badged in the UI. In code, use `app.monitoring.events.EventLogger` and the `app.monitoring.log_buffer.LOG_RECORD_CONTEXT_KEYS` whitelist.

### Advanced settings (dangerous options)

On the admin UI **Advanced settings** page (`http://127.0.0.1:8000/advanced`) you can read and save the global settings file `~/.remote-coder/advanced_settings.json`. **Interface language** (`ui_language`): the default is **English**, and it governs not only the Telegram bot's messages and button labels but the **entire admin UI** (`/`, `/projects`, `/advanced`, `/logs`, `/database`). Switching to **Korean**, saving, and refreshing renders both the admin UI and Telegram responses in Korean. (The admin UI renders English by default and overlays Korean on the client.)

Defaults differ per option (e.g. server-lifecycle Telegram notifications are on by default; `git pull` on server start is off by default); an option left off behaves as if that feature is disabled. Keys used only by older versions are ignored on load (e.g. the removed `auto_pull_on_project_switch`).

> [!WARNING]
> The "immediately apply the request result to main/master and push" option auto-merges AI changes into the integration branch. Unless this is a personal experimental repository, keep the default (off) and verify remote branch protection and your backup policy before enabling it.

- **Immediately apply the request result to main/master and push**: When a Job succeeds through commit and branch push, similar to `/rebase`, it fast-forward-merges that branch into the integration branch (`main` or `master`) and pushes to the remote. If integration fails (conflict, non-ff, etc.), the Job is recorded as failed.
- **SQLite conversation-memory size limit**: When enabled, it targets the whole `conversation_entries` table and deletes oldest rows first. At least one of **max row count** and **max DB size (bytes)** must be a positive number; if both are set, it first meets the row-count limit, then repeats delete/`VACUUM` to meet the size limit. `message_branch_links` orphan links are cleaned up.

## 3) Run it all at once

With the installed CLI, `remote-coder up` handles ngrok startup, webhook registration, and server start in one command. It passes the public ngrok URL to the server as `TELEGRAM_WEBHOOK_PUBLIC_BASE_URL`, so even without restarting the server, the Telegram webhook and `/` command menu for active projects you add/edit in the admin UI are refreshed immediately.

```bash
remote-coder up
```

For multi-bot setups, you can also pass just the public HTTPS Base URL to register the webhook and command menu for each active project with `python scripts/set_webhook.py <URL>`.

On Windows PowerShell you can use the following script:

```powershell
.\run.ps1
```

Or use the batch wrapper that auto-bypasses the PowerShell execution policy:

```bat
run.bat
```

On Windows, `ngrok.exe` must be installed and runnable from PATH before running. Verify:

```powershell
ngrok version
```

- After running the script, just message the bot on Telegram and it works.
- Press `Ctrl+C` to stop the server, which also terminates ngrok.

## 4) Supported commands (MVP)

Refreshing the Telegram registration with `remote-coder up` or `python scripts/set_webhook.py <URL>` registers the same `/` command menu on each project bot that you would configure in BotFather.

- `/start` : Inline menu hub (shortcut buttons for model, monitor, clear, admin items)
- `/help` : Command help (inline buttons for model, monitor, clear items)
- `/model` : Show the default model (select via inline buttons)
- `/model claude` : Change this chat's default model to claude
- `/model codex` : Change this chat's default model to codex
- `/model gemini` : Change this chat's default model to gemini
- `/status` : Select from the recent Job list via inline buttons
- `/status <job_id>` : Query job status
- `/init` : Reset this chat's default-model override, `/clear`, and natural-language Job confirmation-pending state (the bot-bound project is unchanged; SQLite and Git are untouched)
- `/reports` : SQL-aggregate the SQLite conversation memory for the current chat + current working project into a summary report
- `/branch` : Show the currently checked-out branch of this chat's **bound project** repository
- `/branch <name>` : `git switch` only when a local branch exists in the bound project (errors if missing; does not auto-create branches that exist only on the remote)
- `/pull` : Fetch all branch info from the remote and pull the current branch. Also attempts fast-forward updates for other local branches (including main) that are not checked out.
- `/rebase` : Select a branch that exists both locally and on the remote (excluding main/master) via inline buttons, then rebase onto `main` (or `master`) → fast-forward merge → push to remote
- `/rebase <branch>` : Rebase a directly specified branch
- `/pr` : Select a local branch via inline buttons and create a GitHub Pull Request. The PR body includes the requests and AI results exchanged while working on that branch. Requires the GitHub CLI (`gh`) (`gh auth login`).
- `/pr <branch>` : Create a PR for a directly specified branch
- `/clear branch` : Clean up `remote-*` local/remote branches and their linked worktrees, **only in this bot's bound project**
- `/clear worktrees` : Clean up the managed worktrees of **this bot's project** + prune stale entries
- `/clear memory` : Delete only the conversation memory (SQLite) of **this bot's project + the current chat**
- `/stop` : Select an in-progress Job from a list via inline buttons to cancel it
- `/stop <job_id>` : Force-stop the specified Job (only for queued/running states)
- `/fix` : Rework a previous Job's commit message (`commit`) or source (`source`). Overwrites the existing commit with `git commit --amend` and reflects it to the remote with `git push --force-with-lease`. The commit trailer `committed by remote-coder: <id>` keeps the **original Job ID**.
- `/fix commit <job_id>` : Regenerate only the AI commit message and preview it → amend on `y`/`Y` confirmation
- `/fix source <job_id>` : Take a follow-up message as fix instructions and re-run the AI in the same branch worktree → amend + push on `y`/`Y` confirmation
- Replying to a previous bot message with `fix: <instruction>` (or `수정: <instruction>`) immediately shows a source-mode fix confirmation for that Job. The target Job must be in `SUCCEEDED + branch + commit` state.
- `/monitor model` : Based on the current chat's default model, a CLI probe (Claude `claude auth status` / Codex `codex --version` / Gemini `gemini --version`) plus a usage summary observed from local CLI logs. If a Codex session log has `rate_limits`, it shows the 5-hour/weekly remaining rates and reset times; Claude/Gemini show per-model token/request details from local transcript/chat logs.
- `/monitor memory` : SQLite conversation-memory row counts, rows per role, and DB file size for this chat + current **bound project**
- `/monitor branch` : Branch summary of the bound project repository (local/remote counts and lists)
- `/monitor worktrees` : Linked worktree list, detached count, and Remote Coder managed candidate summary
- `/monitor code` : Estimated code file/line counts based on the bound project root (extension whitelist; excludes `.git`, `node_modules`, etc.)
- `/monitor project` : Summary of the project record **bound to this bot** (name, enabled state, path, default model, worktree directory)
- Natural-language message: After agent/plan/ask parsing succeeds, it shows the current project, working branch, model in use, and mode, then creates an AI task (Job) after receiving `y`/`Y` (or an inline confirmation button when advanced settings enable it). Messages starting with the `plan:`/`ask:`/`계획:`/`질문:` prefix (colon `:` or `：`) or `/plan`/`/ask` run in **read-only** plan/ask mode and do not commit/push when the Job runs.

  e.g. `plan: just outline how to refactor the login flow`, `/plan model: codex risks only`, `ask: what's the test command in this repo?`, `/ask the role of JobManager`

Notes:

- A per-chat default model overridden with `/model` is in-memory. On server restart it reverts to the project's `default_model` in the registry.
- The **bound project is always the name bound to this bot instance**. **`/branch`, `/rebase`, `/monitor memory|branch|worktrees|code|project`, etc. operate against that repository.**
- `/init` reverts the per-chat model override and confirmation-pending state (without touching the conversation-memory SQLite or Git repository).
- An AI Job creates a detached worktree from the **current `HEAD` commit** of the **project repository used for the request**, then runs. It creates a working branch and commits **only when the working tree has changes**. If there is a commit, it pushes to `GIT_REMOTE_NAME` (default `origin`). To change the repository branch, switch the local branch first with `/branch <name>`.
- Auto-generated commit messages use the following format:

  ```text
  type: title
  - contents1
  - contents2

  committed by remote-coder: job-id
  ```

  `title` summarizes the functional change in one line, and the first body item describes what the AI agent changed — not the user's raw request or a list of recently modified files. The list of changed files is shown separately in the Job result notification.

- In natural-language messages you can also use the tokens `model: codex`, `model: gemini`, `branch: my-branch`, `no commit`. (The `branch:` value is validated by the same rules as `/branch`. In `plan:`/`ask:` mode, `branch:` and `no commit` are ignored.)
- Natural-language requests do not run immediately after parsing. The confirmation message shows the current project, working branch, and model/mode, and a Job is created only after `y` or `Y` (or an inline confirmation). If a new parseable natural-language message arrives while a confirmation is pending, it silently replaces the previous pending one; if an unparseable input arrives, the pending one is canceled.
- **Conversation memory (SQLite)**: User messages and Job intake/result summaries accumulate in SQLite per the same Telegram chat + same working project. It persists across server restarts. If you previously sent a specific instruction and then send a short follow-up like "start the task", "go ahead", "do that", or "begin", it merges recent records into an AI instruction. If there is no context, the bot sends a guidance message.
- **Reply chains**: For each natural-language request sent as a reply to a previous message, the bodies of ancestor messages remaining in SQLite and the Job-result summaries linked to each message are prepended to the Codex/Claude instruction as a `[Reply chain context]` block. (Restored only if the bot received and stored those messages.)
- You can pass a recent display count, like `/reports 7`. The allowed range is `1–10`, default `5`.
- Writability is checked right after worktree creation. If the AI output contains expressions like read-only/cannot-modify and there is no Git change, it is treated as a **failure**, not a success.
- Task completion/failure messages include a summary of the AI execution result (`stdout`/`stderr`).
- The full raw output is available in the worktree log file (`~/.remote-coder/worktrees/<project>/_logs/<job_id>.log`).

## 5) Per-model usage guides

- Multi-bot / webhook / migration: [`docs/multi-bot-setup.md`](docs/multi-bot-setup.md)
- Claude users: [`docs/claude-guide.md`](docs/claude-guide.md)
- Codex users: [`docs/codex-guide.md`](docs/codex-guide.md)
- Gemini users: [`docs/gemini-guide.md`](docs/gemini-guide.md)
- When a worktree fails as read-only: [`docs/read-only-workspace.md`](docs/read-only-workspace.md)

**Runner operation notes:** The Gemini CLI is wired primarily for non-interactive execution, so expectations may differ from an interactive TUI. The Codex CLI may restrict network or some tool calls depending on its sandbox/approval policy.

## 6) Tests

Multi-bot routing, notification isolation, and project-scoped state are covered by `tests/test_webhook_multibot.py`, `tests/test_bot_instance_manager.py`, `tests/test_project_scoped_state.py`, etc.

```bash
conda activate remote-coder
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q -p pytest_asyncio.plugin -p respx.fixtures
```

## 7) Public repository management

- License: [Apache License 2.0](LICENSE)
- How to contribute: [CONTRIBUTING.md](CONTRIBUTING.md)
- Security policy: [SECURITY.md](SECURITY.md)
- Before opening a Pull Request, run `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 conda run -n remote-coder pytest -q -p pytest_asyncio.plugin -p respx.fixtures`.
