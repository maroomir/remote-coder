# Remote AI Coder

Run Claude Code, Codex, Gemini, or Ollama on your local development machine by sending a Telegram message. Remote AI Coder isolates each request in a Git worktree, commits the result on a separate branch, and reports the outcome back to Telegram.

*English: this document · 한국어: [README.ko.md](README.ko.md)*

> [!WARNING]
> This is a local automation tool with access to AI CLIs, Git, and your filesystem. Keep it private, use Telegram allowlists, and do not expose the server or admin UI to the public internet.

## What You Get

- Telegram as a lightweight remote control for local coding agents.
- One Telegram bot per registered project, with project-scoped allowlists and settings.
- Request-specific Git worktrees, branch creation, commit, push, and result notifications.
- Claude, Codex, Gemini, and Ollama runners behind the same job flow.
- Reply-linked jobs continue the same AI CLI session, so follow-ups build on prior context.
- Local admin UI for project setup, advanced settings, logs, and conversation memory.
- Read-only `plan:`, `ask:`, and `research:` modes when you want analysis without commits. PLAN mode asks open decisions through inline buttons first, then finalizes the plan from your answers; RESEARCH mode asks the selected AI CLI to use internet search when useful.
- Declarative mode addons: drop a YAML file under `~/.remote-coder/addons/` to add your own read-only prompt-preset mode without code changes. See [docs/mode-addons.md](docs/mode-addons.md).

## Quick Start

Install the CLI:

```bash
pip install remote-coder
```

Or install the latest development version from source:

```bash
pip install git+https://github.com/maroomir/remote-coder.git
```

Check your local tools, then start everything:

```bash
remote-coder doctor
remote-coder up
```

Open `http://127.0.0.1:8000/`, add your first project, and message the project bot in Telegram. `remote-coder up` runs the server, starts the ngrok tunnel, registers webhooks, and refreshes the Telegram command menu. Use `remote-coder up --no-tunnel` when you only want the local server.

## Requirements

- Python 3.11+
- `ngrok` or another HTTPS tunnel for Telegram webhooks
- One Telegram bot token per project
- Allowed Telegram Chat IDs, and optionally User IDs
- At least one local AI CLI/provider: `claude`, `codex`, `gemini`, or `ollama`
- A local Git repository to automate
- GitHub CLI (`gh`) authenticated with `gh auth login` when using `/pr`

## How It Works

```text
Telegram message
 -> FastAPI webhook /telegram/webhook/{sha256-prefix16}
 -> project-bound bot instance and allowlist check
 -> command parser or natural-language confirmation
 -> JobManager
 -> Git worktree
 -> Claude / Codex / Gemini / Ollama runner
 -> branch, commit, push, and Telegram result
```

Each project uses its own bot. The webhook path contains the first 16 hex characters of `SHA-256(bot token)`, never the raw token. Natural-language jobs show the target project, branch, model, and mode before running, then wait for confirmation.

## Everyday Commands

| Command | Purpose |
|---|---|
| `/start`, `/help` | Open the menu or command help |
| `/model` | View or change the chat's default model |
| `/status [job_id]` | Inspect recent or specific jobs; running jobs show the latest captured AI output when available |
| `/log [job_id]` | Pick a recent job or show captured AI stdout for a specific job |
| `/branch [name]` | Show or switch the bound project's local branch |
| `/pull` | Fetch remotes and pull the current branch |
| `/rebase [branch]` | Rebase and fast-forward a completed branch into `main` or `master` |
| `/pr [branch]` | Create a GitHub PR from a committed succeeded Job branch with `gh` |
| `/fix ...` | Rework a previous job's commit message or source |
| `/monitor ...` | Inspect model, memory, branch, worktree, code, or project status |
| `/clear ...` | Clean managed branches, worktrees, or conversation memory |
| `/stop [job_id]` | Cancel a queued or running job |
| `/init` | Reset chat-local model and pending confirmations |

Calling `/pr` without a branch lists only remote branches produced by committed succeeded Jobs in the current project and Telegram chat. Direct `/pr <branch>` calls enforce the same ownership check and verify that the branch still exists on the configured Git remote. Install the [GitHub CLI](https://cli.github.com/) and run `gh auth login` before using this command.

Natural-language examples:

```text
Fix the login validation bug with model: codex
ask: model: ollama explain the parser flow
plan: outline the migration before changing code
/ask what test command does this repo use?
/research compare current Telegram webhook security guidance
수정: 방금 작업에서 README 문구만 더 간결하게 바꿔줘
```

## Configuration

Day-to-day setup happens in the local admin UI. Files live under `REMOTE_CODER_HOME`, defaulting to `~/.remote-coder`:

- `projects.json` stores project records, bot tokens, allowlists, root paths, and default models.
- `advanced_settings.json` stores global behavior such as timeouts, sandbox mode, language, worktree retention, and memory limits.
- `worktrees/<project>/` contains managed job worktrees and logs.
- `ollama_sessions/` stores local Ollama reply-chain transcripts for session continuity.
- On server startup, queued Jobs stored in SQLite are rerun; Jobs that were running when the server stopped are marked failed with `server_restart` for `/status` review.

Useful overrides: `REMOTE_CODER_HOME`, `PROJECTS_CONFIG_PATH`, `CONVERSATION_DB_PATH`, `JOB_DB_PATH`, `OLLAMA_HOST`, and `REMOTE_CODER_OLLAMA_DEFAULT_MODEL`.

## Security Notes

- Treat `~/.remote-coder/projects.json` as a secret; bot tokens are stored in plain text.
- Keep the admin UI on localhost.
- Do not paste secrets or sensitive code into Telegram messages.
- Dangerous runner modes such as Claude `--dangerously-skip-permissions`, Gemini `--approval-mode yolo`, Codex `danger-full-access`, and Ollama-generated patches can modify local files.
- See [`SECURITY.md`](SECURITY.md) before publishing, exposing, or sharing a deployment.

## More Docs

- Multi-bot setup and migration: [`docs/multi-bot-setup.md`](docs/multi-bot-setup.md)
- AI runners: [`docs/ai-runners.md`](docs/ai-runners.md)
- Read-only worktree troubleshooting: [`docs/read-only-workspace.md`](docs/read-only-workspace.md)
- Contributing: [`CONTRIBUTING.md`](CONTRIBUTING.md)

## Development

```bash
conda env create -f environment.yml
conda activate remote-coder
python -m pip install -e ".[dev]"
remote-coder up --no-tunnel --reload
```

Run the test suite:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 conda run -n remote-coder pytest -q -p pytest_asyncio.plugin -p respx.fixtures
```

License: [Apache License 2.0](LICENSE)
