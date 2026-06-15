# Changelog

*English: this document · 한국어: [CHANGELOG.ko.md](CHANGELOG.ko.md)*

This file follows the [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format, and version numbers follow [Semantic Versioning](https://semver.org/).

When compiling history in one pass, it helps to read the Git log alongside the docs and group by feature. The **source of truth is always `git log`, the release tags, and previous versions of this file.**

## [Unreleased]

### Added

- **Full AI output from job status**: a `/status <job_id>` detail panel offers a **View full log** button that delivers the complete AI stdout (not just the tail) as paginated Telegram messages.

## [0.5.2] — 2026-06-15

### Added

- **Read-only RESEARCH mode**: `/research`, `research:`, and `조사:` requests run the selected AI CLI with repository context and internet-search guidance in a detached worktree, without creating commits or pushing branches.

### Changed

- **Clearer mode guidance**: `/start` presents AGENT, PLAN, ASK, and RESEARCH actions in a compact layout, and mode help no longer mentions the removed text-confirmation flow.
- **Actionable GitHub CLI setup**: Telegram PR flows, CLI diagnostics, and the admin dashboard now explain how to install and authenticate `gh` when it is unavailable.
- **Repeatable release publishing**: Release automation can safely recreate an existing GitHub Release and skips PyPI upload when the version is already published, making workflow re-runs reliable.

## [0.5.1] — 2026-06-14

### Added

- **Telegram lifecycle reactions**: The bot reacts to the original request when a job is queued and updates the reaction when it succeeds, fails, or is cancelled, without allowing reaction delivery failures to affect the job.
- **Persistent command menu and action colors**: Project bots pin Telegram's slash-command menu beside the message input and use Bot API button styles for primary, success, and destructive actions.

### Changed

- **Job results edit the accepted message**: Results that fit in one Telegram message now replace the accepted/heartbeat message in place. Long results or failed edits fall back to separate messages after removing the stale Stop button.
- **Concise chat guidance**: `/start`, `/help`, and monitoring output now use shorter, readable sections and lists. Help buttons are informational only and no longer execute commands.

### Fixed

- **Non-blocking startup work**: Repository pulls and Telegram startup notifications run after HTTP readiness, and background failures are logged without breaking application shutdown.
- **Claude reply-session fallback**: ASK, PLAN, and other jobs that run in a newly created worktree no longer pass a cwd-scoped Claude `--resume` token that the CLI cannot find. They keep the logical Session ID and injected reply context, while native resume remains enabled when the existing linked worktree is reused.

## [0.5.0] — 2026-06-13

### Added

- **PLAN mode inline decisions**: When a `/plan` request depends on choices only you can make, the model now surfaces them first as a structured block, and the bot asks each decision through Telegram inline buttons (one question at a time) before producing the final plan. Your answers are injected into a second PLAN run, so it works identically across Claude, Codex, and Gemini. If the model has no open decisions, the plan is delivered directly as before.
- **Run-plan button**: A successful PLAN result now carries a **Run plan** inline button. One tap submits an AGENT job that implements the approved plan (the plan text and original request are injected as context), so you go from plan to implementation without retyping.
- **Job heartbeat**: While a job runs, the "Job accepted" message updates roughly once a minute with an elapsed-time line (`⏳ Running (Nm elapsed)`), so long runs no longer look stalled. The message is restored when the job finishes.

### Fixed

- **Codex commit message generation**: Codex can now generate AI-written commit messages from temporary directories by skipping the Git repository check, and failures include a concise stderr preview in operator logs.
- **Codex session resume options**: Codex resume jobs now pass `--model` and `--sandbox` before the `resume` subcommand, matching the current CLI parser and avoiding `unexpected argument '--sandbox'` failures.
- **Scoped and reliable `/pr` flow**: PR choices now include only live remote branches from succeeded Jobs in the current project and Telegram chat, including branches no longer present locally. Direct branch arguments receive the same ownership and remote-existence validation, successful committed Job notifications include an Open PR button, existing PRs are reused, and missing/timed-out/unauthenticated `gh` failures return actionable Telegram errors instead of escaping the webhook.
- **Partial output on timeout/cancel**: When a runner is killed by a timeout or cancellation, the partial stdout/stderr it produced is now saved to the job log and summarized in the failure notification, instead of being discarded with only a one-line error.
- **Reply-linked AI sessions**: Jobs connected through Telegram replies now continue the *same* AI CLI session instead of starting fresh every message. Each reply chain is anchored to its root message and assigned a session id (persisted in SQLite and linked to job ids); runners resume natively — Claude via `--session-id`/`--resume`, Codex via `codex exec resume <id>` (id captured from its rollout file), Gemini via `--resume <id>` when available, otherwise falling back to the existing reply-context injection. Native Claude resume relies on the chain reusing the same worktree (the normal branch-bound reply flow). `/clear memory` also clears stored sessions.
- **Visible Session ID**: The session id is now shown to the user so they can verify a reply chain stays on one session — on the job accepted and job result messages (right under Job ID, monospace), in the `/status <job_id>` detail, on the `/reports` latest job result, and as a `Sessions:` count in `/monitor memory`.
- **Easy setup wizard**: The admin dashboard now guides first-time users through a 4-step flow — verify bot token, auto-detect the Telegram chat, and create the project — so a new project can be live in about a minute. Backed by new localhost-only `POST /api/setup/validate-token` and `POST /api/setup/detect-chat` endpoints.

### Changed

- **Admin UI redesign**: All admin pages share a responsive sidebar dashboard layout and a single stylesheet (`admin.css`) with a refreshed, modern theme. The home page is now a dashboard; project registration, advanced settings, logs, and the data browser keep their behavior under the new shell.
- **Telegram message styling**: Outbound bot messages are now rendered BotFather-style with Telegram message entities — bold titles and section headings, monospace Job ID/branch/commit values — while the message text itself stays unchanged.
- **In-chat panels edit in place**: Tapping a menu/submenu button now edits the existing message instead of sending a new one, with a lightweight toast on actions and consistent ‹ Back / ✖ Close navigation. The `/status <job_id>` view gains status-aware action buttons (Stop, or Open PR / Rebase).
- **Button-only confirmations**: Job, fix, and clear confirmations always use inline Yes/No buttons; the `y`/`Y` text path and the related advanced setting were removed.
- **Slimmer Advanced Settings**: Removed five rarely-used options — confirmation-button toggle, server start/stop notification toggle, `/status` recent-job count, ambiguous follow-up conversation count, and reply-snippet max length — and hardcoded them to their previous defaults. Existing config files drop the old keys on load.

### Security

- **Random webhook secrets**: New projects now receive a unique 256-bit URL-safe Telegram webhook secret when the admin UI leaves the field blank, replacing the shared predictable default.
- **Per-project job serialization**: AGENT, PLAN, ASK, and source-fix jobs for the same project now run under one in-memory project lock, preventing concurrent reuse or mutation of a linked worktree. Jobs for different projects remain independent.

## [0.4.4] — 2026-06-10

### Added

- **`/fix` command workflow**: `/fix` now requires replying to a job result message, resolves the target job from that context, and shows clearer instructions and error feedback in Telegram.
- **Start command version**: `/start` responses now include the running application version.
- **Gemini usage monitoring probe**: Usage monitoring performs a live Gemini CLI model probe and reports observed model name and token usage when available.

### Changed

- **CLI and script messages**: CLI output, tunnel messages, and install/dev/prepare scripts now use English for consistent operator-facing text.
- **Codex model picker order**: `/model codex` detail buttons now list `gpt-5.5` first in the Codex catalog.
- **Agent rule docs**: Consolidated `.cursor/rules/` and `AGENTS.md`; removed legacy `.clinerules/` copies.

## [0.4.3] — 2026-06-09

### Added

- **Conversation reply snippet length**: Advanced settings now let you configure how many characters are kept from quoted Telegram replies in conversation context, with validated min/max bounds.
- **Development script**: Added `./scripts/dev.sh` for editable installs and local server reload without tunnel or webhook registration.
- **Consolidated AI runner docs**: Replaced separate Claude/Codex/Gemini guides with unified `docs/ai-runners.md` (and Korean counterpart), plus refreshed multi-bot and read-only workspace troubleshooting guides.

### Changed

- **Per-project worktree paths**: Worktree directories are now derived from the project name under `REMOTE_CODER_HOME`; legacy state file paths are resolved automatically.
- **Documentation cleanup**: Simplified English and Korean README files, removed `.env.example`, and clarified that the project registry and admin UI are the configuration source of truth.

### Fixed

- Natural-language job requests no longer reuse job IDs parsed from quoted Telegram replies; each new request gets a fresh ID.
- Claude ASK/PLAN mode no longer passes `--permission-mode plan`, so full responses stream to stdout and appear in Telegram summaries again.

## [0.4.2] — 2026-06-09

### Added

- **First-time setup in the admin UI**: When no projects are registered, the admin home screen now shows a setup card with prerequisite checks and a direct path to adding the first project.
- **Shared prerequisite diagnostics**: Added a reusable diagnostics module and `/api/prerequisites` endpoint for checking ngrok configuration and installed AI CLIs.

### Changed

- **Simplified setup flow**: Removed the interactive `remote-coder init` command. New installations now start with `remote-coder up`, then complete project registration in the local admin UI.
- **Documentation cleanup**: Updated English and Korean setup docs to explain that the project registry is the source of truth, while `.env` is optional seed configuration.

### Fixed

- `remote-coder up` now gives a first-project setup prompt instead of treating an empty registry as a webhook registration failure.

## [0.4.1] — 2026-06-07

### Added

- **One-command install/run**: After `pip install remote-coder`, start without Conda using `remote-coder init` (interactive setup wizard) and `remote-coder up` (ngrok tunnel + Telegram webhook registration + server, all at once). Server-only is `remote-coder up --no-tunnel`; prerequisite checks (ngrok, AI CLIs) are `remote-coder doctor`. (The CLI has three commands: `init`/`up`/`doctor`.) pipx, uv, and `curl | bash` ([`scripts/install.sh`](scripts/install.sh)) are also available as alternatives.
- **Global config location**: Loads `.env` from `REMOTE_CODER_HOME` (default `~/.remote-coder`) so it does not depend on the working directory. When developing inside the repo, the current directory's `.env` takes precedence.
- **Automatic PyPI publishing**: Pushing a tag (`vX.Y.Z`) makes GitHub Actions upload to PyPI via secret-less Trusted Publishing (OIDC) and create a GitHub Release.

### Changed

- Moved ngrok handling into `app/tunnel.py` and extracted active-project webhook/command registration into `register_all_enabled_projects`, shared by `remote-coder up` and `scripts/set_webhook.py`.

### Fixed

- Fixed the admin UI breaking when installed via `pip install`. Package data (`app/admin/templates/*.html`, `app/admin/static/*.js`, `app/admin/static/icons/*.svg`) is now included in the build artifacts.

## [0.4.0] — 2026-06-07

### Changed

- **AI runner restructuring**: Extracted the common Claude/Codex/Gemini execution flow into `BaseCliRunner`, removing code duplication across runners.
- **Simplified AI model branching**: Replaced scattered `if/elif` chains with dictionary dispatch to simplify runner selection.
- **Model-usage monitoring as a strategy**: Reorganized per-model usage tracking into a `ModelUsageProvider` strategy pattern.
- **Notifier protocol separation**: Cleanly separated message formatting and delivery roles via a `Notifier` protocol.
- **Telegram webhook/command restructuring**: Decomposed the webhook handler by responsibility and reorganized command modules into a `commands/` package.
- **Git plumbing consolidation**: Consolidated duplicated worktree/rebase Git plumbing into a single service.
- **i18n message cleanup**: Applied translations to task notifications, server status, and model-provider selection messages and cleaned up the English defaults.
- **ASCII commit messages**: Strengthened formatting and validation so auto-generated commit messages follow ASCII rules.

### Fixed

- Cleaned up unused classes, methods, and imports to reduce codebase noise.

## [0.3.3] — 2026-06-06

### Added

- **Stronger model-ID handling**: Extended the Claude/Codex/Gemini runners and related components to carry model IDs.
- **`/fix` command**: Added a flow to fix the commit message or request a source rework based on a recent task result.

### Fixed

- Completed follow-up tasks now correctly update the parent task's commit hash and changed-file list.
- Adjusted so model-selection buttons are returned only for incomplete model commands.
- Ensured the task repository state needed for fix-candidate recovery is preserved.
- Fixed Gemini ASK/PLAN mode execution to use the `--skip-trust` flag.
- Fixed AI commit generation to use the selected model and avoid mixing the Job ID into the fallback message.

## [0.3.2] — 2026-05-25

### Added

- **Admin UI localization**: Switched the local admin UI (`/`, `/projects`, `/advanced`, `/logs`, `/database`) to English by default, and made it render in Korean on the client when `ui_language` is set to Korean in advanced settings (`app/admin/static/i18n.js` catalog). The current language is injected into page responses, following the same global setting as Telegram.

### Changed

- Standardized the user-facing strings in the admin UI backend (table labels, webhook guidance, masked-token display values) to English. Unified error/validation messages to English.

## [0.3.1] — 2026-05-22

### Added

- **Per-language response improvements**: Strengthened help and conversation-context output to reflect the language setting.

### Changed

- **Default language setting**: Kept the default response language as English and cleaned up the flow for selecting Korean in advanced settings.
- **Confirmation message wording**: Polished wording that mixed Korean and English in the confirmation step.

### Fixed

- Adjusted monitoring behavior to match the latest state.

## [0.3.0] — 2026-05-15

### Added

- **PLAN/ASK task modes**: Added task modes that distinguish implementation tasks, plan requests, and question answers in both natural language and slash commands.
- **PLAN/ASK confirmation flow**: Made natural-language requests in PLAN/ASK mode also confirm the current project/branch/model/mode before running.
- **Pull projects on server start**: Added an operational setting to pull registered projects up to date on server startup.

### Changed

- **AI runner instruction handling**: Strengthened the Claude/Codex/Gemini execution instructions to reflect task-mode context.
- **`/start` menu**: Simplified the start screen around help and mode guidance, with direct navigation to key subcommands.
- **Model-selection menu**: Moved the model inline buttons under the admin section to simplify the command menu structure.

### Fixed

- Fixed so that calling `/clear` and `/monitor` without arguments shows the inline button menu.
- Prevented possible duplicate execution of `/rebase` callbacks with an idempotency lock and an early response.
- Fixed follow-up requests replying to a bot message to correctly link to the original Job ID and conversation history.
- Fixed argument-less `/plan` and `/ask` commands to switch into input-waiting mode.

## [0.2.3] — 2026-05-12

### Added

- **Telegram command menu**: Also call `setMyCommands` during webhook registration, registering in the default, private-chat, and allowed-chat scopes so supported commands appear in the Telegram client just by typing `/`.
- **Admin dashboard summary grid**: Added project/task/Git status summary cards to the admin UI home screen.
- **Server lifecycle notification setting**: The admin UI can configure whether to send Telegram notifications on server start/stop.

### Changed

- **Telegram message layout**: Applied a structured layout to command response messages for readability.
- **`/model` confirmation message**: Updated the model-change confirmation message format.

### Fixed

- Fixed the bot command menu not appearing when typing `/` in the Telegram client.
- Fixed a branch-checkout conflict during Git worktree creation.
- Fixed inline-button flag activation not correctly replacing the existing Y/y confirmation prompt.

## [0.2.2] — 2026-05-11

### Added

- **Admin UI — advanced settings**: Whether to use inline-button Yes/No responses, task timeout, and auto-deleting a branch after rebase can be adjusted in advanced settings.

### Changed

- **Webhook operations**: Adding or editing a project in the admin UI refreshes the Telegram webhook configuration without a restart.
- **Rebase diagnostics**: Strengthened diagnosis of rebase-failure causes, such as missing remote references.

### Fixed

- Fixed a possible `scope_project` local-variable initialization error during callback-query handling.
- Fixed previous task context possibly being lost when replying to a bot message.
- Hardened the Git integration where rebase occasionally failed.
- Prevented the user prompt's raw text from leaking into the auto-commit title.

## [0.2.1] — 2026-05-09

### Changed

- **Admin UI — project registration**: Removed the multi-bot webhook guidance card (Base URL preview, etc.). The Telegram column in the registration list shows only a masked bot token and a badge for whether a webhook secret is set. Grouped the webhook secret and allowed User IDs into a collapsible "optional items" section in the add/edit form to simplify the screen.

### Added

- **Project-creation defaults**: In the admin API `POST /api/projects`, omitting or leaving `webhook_secret` empty stores `optional-secret`. The omit/empty-string behavior when editing via `PUT` is unchanged.

## [0.2.0] — 2026-05-09

A bundle of the pre-multi-bot registry format and operability-focused changes.

### Added

- **Legacy registry augmentation**: When `projects.json` lacks or has empty `bot_token`/`allowed_chat_ids`, on load it reads `.env` via `python-dotenv` and fills/validates with `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_CHAT_IDS`, `TELEGRAM_ALLOWED_USER_IDS`, and (optionally) `TELEGRAM_WEBHOOK_SECRET`. This enables booting and webhook registration without fixing the existing file all at once.
- **CI**: A workflow that automates build, checks, and a GitHub Release on `v*.*.*` tag push.

### Changed

- **Settings cleanup**: Removed the deprecated `auto_pull_on_project_switch` setting and its related load logic, docs, and admin UI exposure.

### Fixed

- Strengthened regression tests for the legacy registry load behavior.

## [0.1.0] — 2026-05-09

The feature bundle corresponding to the first PyPI/Git release. Summarizes, from a user's perspective, the cumulative changes from initial bootstrap to multi-bot/packaging in the repository commit history.

### Added

- **FastAPI server / webhook**: Receive Telegram Bot webhooks, respond quickly, then run a background task flow.
- **Job management**: Queue, states (`queued`, `running`, `succeeded`, `failed`, `cancelled`, etc.), timeouts, per-stage failure recording, Job ID uniqueness.
- **Git worktree isolation**: AI work in a per-request worktree instead of the main working directory; branch-name specification or safe auto-generation; skip branch/commit/push when there are no changes.
- **AI runners**: A shared interface/factory for Claude Code, Codex CLI, and Gemini CLI; collection of stdout, exit code, and execution time.
- **Auto commit**: `type: title` format, body bullets, `committed by remote-coder: <job-id>` footer; optional AI-based commit-message augmentation.
- **Telegram commands / parser**: Slash commands, natural-language request parsing; natural language creates a Job only after a summary confirmation with `y`/`Y`.
- **SQLite conversation/memory**: Store task-result summaries; link previous Job context via reply chains.
- **`/init`**: Reset the chat's model override and pending confirmation state (without changing SQLite or Git).
- **Inline keyboards**: Button UI when `/model`, `/status`, `/branch`, `/rebase`, `/stop`, etc. are called without arguments; callbacks route through the existing slash-command path.
- **Git helper commands**: Branch query/switch, rebase/conflict mitigation, worktree cleanup (`clear`), remote branch sync (`/pull`), GitHub PR creation (`/pr`), branch/repo summaries for monitoring (`/monitor`, etc.).
- **Admin UI**: Project and advanced-settings pages, in-memory log buffer and log view, DB browsing, summary/statistics/model-usage display.
- **Monitoring / event logs**: Structured logging; use `EventLogger` at the Telegram/Job/Git/Runner boundaries; record only previews per the policy that forbids exposing secrets/full paths in message bodies.
- **Token/model metadata**: Store observed model name and token usage in Job results; strengthen Codex/Claude/Gemini usage/quota tracking.
- **Installable package**: `pyproject.toml`-based build, console entry point `remote-coder`.
- **Operational docs**: Example environment variables, agent rules (`AGENTS.md`, `.clinerules/`, `.cursor/rules/`), release runbook (`RELEASE.md`), and CLI setup guides for Gemini and others.
- **Multi-bot / project registry**: Per-project bot token and allowlist; webhook path routed by the **first 16 hex chars** of the bot token's SHA-256 digest (no plain-text token in the URL). Per-instance notification/auth/`CommandContext` binding via `BotInstance` / `BotInstanceManager`.
- **Per-project state**: Separate chat state (Jobs, confirmations, model preferences) per bot-bound project; filter so a single user talking to multiple bots does not get mixed task lists.

### Changed

- **Project selection UX**: Removed the `/project` flow for switching repositories from chat and simplified to a **bot (webhook) = one registered project** model. Project lists/monitoring are organized via `/monitor`, etc.
- **`/start` / help**: Adjusted project selection/button layout; simplified `/help` toward a text list, among iterative UX improvements.
- **Commit/notification messages**: Clarified the commit-message rules and completion-notification format; removed unnecessary inline buttons from some messages such as model-change confirmation.
- **Docs/rules sync**: Reflected security (Telegram/registry token handling), Git/task/runner policies, and the minimal-test/comment policy in `PLAN.md` and the rule files.

### Fixed

- Many Telegram edge cases in the webhook-registration script, callback handling, help, and model commands (e.g. buttons not showing on callback, notification length/repeat-send issues).
- Git/CLI integration bugs in rebase, branch clear, the Codex sandbox, etc.
- Behavior fixes that reduce user confusion, such as read-only guidance wording and handling of no-change tasks.

### Security / operational notes

- The allowlist is **per registered project (bot)**. The registry file's tokens are designed to be storable in plain text, so file permissions and leak prevention are prerequisites.
- User messages are never passed directly to a shell; subprocesses use list arguments, explicit `cwd`, and timeouts.

[Compare initial commit…`v0.1.0` tag](https://github.com/maroomir/remote-coder/compare/3931251...v0.1.0)
