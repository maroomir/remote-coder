# AGENTS.md

This document gives AI coding agents the project-specific context and workflow needed to work effectively in `remote-coder`.

## Project Identity

`remote-coder` is a FastAPI automation service that lets an allowed Telegram user run local AI coding tools remotely. Each registered project can use its own bot token and allowlist; the webhook path uses the **first 16 hex characters** of the SHA-256 digest of that token as the routing key (not the raw token). After routing, **bot instance = project context**: slash commands, confirmations, model prefs, recent jobs, and natural-language parsing are scoped to that project; shared services (job manager, Git worktree service, parser, command registry) operate with that binding.

Core flow:

```text
Telegram Message
  -> FastAPI Webhook (/telegram/webhook/{sha256_prefix16})
  -> BotInstanceManager -> per-bot Auth / Notifier / CommandContext.project_name
  -> Command Parser
  -> Job Manager
  -> Git Worktree
  -> AI Runner (Claude / Codex / Gemini)
  -> Git Commit
  -> Telegram Notification
```

## Source of Truth

- The user's latest explicit instruction overrides project documents.
- `PLAN.md` defines product goals, MVP scope, requirements, architecture, and roadmap.
- `.clinerules/` and `.cursor/rules/` define project-wide development rules for Cline and Cursor.
- `AGENTS.md` defines AI-agent workflow, checklists, and final reporting expectations.
- `CLAUDE.md` is the Claude Code entry point and references the rule files.
- Existing source files and tests override intended architecture notes. If implementation and documentation disagree, investigate before editing.

Consult sources in this order for non-trivial work:

1. The user's latest explicit instruction.
2. `PLAN.md`.
3. `.clinerules/`.
4. `.cursor/rules/`.
5. `AGENTS.md`.
6. Existing code and tests.

If documents conflict in a way that could change behavior, ask the user before editing. Clear typos or stale wording can be fixed while preserving intent.

## Core Principles

- Keep the MVP flow safe, observable, and testable.
- Webhook handlers must respond quickly; long-running AI work belongs in background jobs.
- Validate Telegram Chat ID/User ID before executing commands or creating jobs.
- Never hard-code bot tokens, API keys, private Chat IDs, credentials, or local secrets.
- Never execute user messages directly as shell commands.
- Keep Git, Telegram, subprocess, and AI CLI details behind service or adapter boundaries.
- Use OOP and GoF patterns when they reduce real complexity: Strategy/Factory for AI runners, Adapter for external tools, Command for Telegram commands, Facade/Orchestrator for job execution.
- Prefer small, focused modules over large catch-all files.
- Follow `.clinerules/05-agent-behavior.md`: surface assumptions, prefer simple solutions, make surgical changes, and define verifiable success criteria.
- Follow `.clinerules/15-clean-code.md`: optimize for readability, maintainability, testability, and consistent naming/structure.
- Follow `.clinerules/60-comments-policy.md`: add minimal comments only for why, security, constraints, tradeoffs, or non-obvious contracts.

## Agent Behavior

For non-trivial work, state assumptions and success criteria before editing. Ask when ambiguity could change product behavior, architecture, security, or verification.

Write the minimum code or documentation needed to satisfy the request:

- Do not add unrequested features, configuration, flexibility, or extension points.
- Do not abstract single-use code.
- Do not add defensive branches for scenarios that cannot happen in the current design.
- If the implementation becomes much larger than the problem demands, simplify before finalizing.

Keep changes surgical:

- Touch only files and lines required by the request.
- Do not improve adjacent code, comments, formatting, or naming unless directly required.
- Match existing style.
- Remove unused imports, variables, functions, files, or tests introduced by your own changes.
- Mention unrelated dead code or cleanup opportunities instead of changing them.

## Pre-Work Checklist

Before code changes, check:

- [ ] Is the task inside `PLAN.md` MVP or extension scope?
- [ ] Are assumptions, ambiguous interpretations, and tradeoffs clear?
- [ ] Are success criteria and verification steps defined?
- [ ] Does the change respect `.clinerules/` and `.cursor/rules/`?
- [ ] Does the design preserve clear responsibility boundaries?
- [ ] Would Strategy, Adapter, Factory, Command, Facade, State, or Repository simplify real variability?
- [ ] Is the change avoiding unrequested features, configurability, and abstraction?
- [ ] Could secrets or private IDs be hard-coded by accident?
- [ ] Does the task include subprocess execution, file deletion, Git mutation, or other risky operations?
- [ ] Does it preserve worktree and branch policy?
- [ ] Does every planned edit trace directly to the user request?
- [ ] Are new comments limited to why, security, constraints, or tradeoffs?
- [ ] Are tests or docs required?
- [ ] If rules change, should `.clinerules/`, `.cursor/rules/`, `AGENTS.md`, or `CLAUDE.md` be updated together?

## Post-Work Checklist

Before finalizing, check:

- [ ] The implementation satisfies the user request.
- [ ] Relevant tests were added or updated when needed.
- [ ] Verification was run, or limitations and residual risk are stated.
- [ ] Success criteria are met.
- [ ] Unused imports, variables, functions, tests, and doc mismatches introduced by the change are cleaned up.
- [ ] No unrelated refactors, formatting churn, or surrounding cleanup is mixed in.
- [ ] New environment variables, commands, or config files are documented.
- [ ] Development rules, security policy, workflow, or directory structure changes are reflected in rule docs.
- [ ] Product requirement or roadmap changes are reflected in `PLAN.md`.

## Architecture Guidelines

Recommended structure:

```text
app/
  main.py                     # FastAPI application creation
  config.py                   # Environment and settings
  models.py                   # Shared models
  telegram/
    webhook.py                # Webhook router
    bot_instances.py          # Per-bot notifier, auth, token_hash routing
    notifier.py               # Telegram message delivery
    commands.py               # /help, /model, /status, etc.
    parser.py                 # Message parsing
    conversation.py           # SQLite conversation context
    confirmations.py          # User confirmation flow
    model_preferences.py      # Model selection state
  jobs/
    manager.py                # Job facade/orchestrator
    store.py                  # Job store
    schemas.py                # Job models
  git/
    service.py                # Git/worktree operations
    branch_naming.py          # Branch naming policy
    commit_message.py         # Commit message format
    ai_commit.py              # AI run + commit orchestration
  ai/
    base.py                   # AiRunner interface
    claude.py                 # Claude Code runner
    codex.py                  # Codex runner
    gemini.py                 # Gemini runner
    factory.py                # Runner factory
  projects/
    registry.py               # Project path/settings registry
  security/
    auth.py                   # Allowlist validation
  monitoring/
    log_buffer.py             # Ring buffer and MemoryLogHandler
    events.py                 # EventLogger facade
  admin/
    router.py                 # Admin UI router
tests/
configs/
  projects.example.yaml
```

Start with the smallest useful version of this structure. Add deeper layers only when there is a concrete feature or testability need.

## FastAPI and Telegram

- Use Pydantic models for request validation.
- Separate routers, services, settings, models, and adapters.
- Natural-language job requests must show current project, target branch, and model, then wait for `y` or `Y` confirmation before creating a job. The effective project is the bot instance's bound project (no `/project` command).
- `/init` resets the chat's default model override and pending confirmation state. It must not alter SQLite conversation memory or Git repositories.
- Commands with selectable options (`/model`, `/status`, `/branch`, `/rebase`, `/stop`) should show inline buttons when called without arguments and route callbacks through the existing slash-command path.

## Git and AI Runner Rules

- AI jobs run in separate worktrees created from the requested project repository's current `HEAD`.
- Do not modify the main working tree, default branch, or currently checked-out branch for AI jobs.
- If there are no changes, do not create a branch, commit, or push.
- If changes exist, create a branch, commit, and push to the configured remote (`origin` by default).
- Automatic commit messages must use `type: title`, bullet body lines, and `committed by remote-coder: <job-id>`.
- The commit title must summarize the functional change. The first bullet must describe what the AI agent changed.
- Store commit hash, branch name, changed files, observed model details, and token usage when available.
- Claude/Codex/Gemini runners share a common interface and return stdout, stderr, exit code, start time, and end time.
- Use list-based subprocess arguments, explicit timeout, and explicit `cwd`; avoid `shell=True`.

## Event Logging

Use `app.monitoring.events.EventLogger` for structured logs at Telegram, Job, Git, and Runner boundaries.

```python
from app.monitoring.events import EventLogger

logger = EventLogger("app.telegram.webhook")
logger.info("message_received", extra={"chat_id": chat_id, "job_id": job_id})
```

- Pass only keys defined in `LOG_RECORD_CONTEXT_KEYS` through `extra`.
- Log Telegram user message text only as a first-line preview of at most 80 characters.
- Do not log secrets, bot tokens, or full project absolute paths in message bodies.

## Testing and Verification

- Before running tests or server commands, use the `remote-coder` Conda environment.
- Default verification command: `conda run -n remote-coder pytest -q`.
- Prefer focused tests first for narrow changes, then broaden when shared behavior changes.
- Mock Telegram API calls, AI CLI calls, and real Git repositories in unit tests.
- Do not mutate user repositories, create real commits, call external networks, or invoke real AI CLIs in default tests.
- Prioritize tests for command parsing, authentication, job state transitions, Git worktree behavior, runner result handling, notifier formatting, and pattern objects.

## Rule Synchronization

Review rule updates when changing:

- Security policy.
- Directory structure.
- Testing strategy.
- Git/worktree/branch policy.
- AI Runner execution behavior.
- OOP or GoF pattern guidance.
- Telegram command handling.
- Job state model or workflow.
- Comment/docstring policy.
- Agent completion reporting.

Update targets:

- Product requirements or roadmap changes -> `PLAN.md`.
- Global development rules -> `.clinerules/` and `.cursor/rules/`.
- AI-agent procedure or checklist changes -> `AGENTS.md`.
- Claude Code rule entry point changes -> `CLAUDE.md`.

## Final Report Format

When work is complete, summarize:

- Changed files.
- Implemented behavior or written documentation.
- Security/configuration notes.
- Verification commands and results, or why verification was limited.
- Whether rule documents were updated.
- Remaining TODOs or follow-up work.

Keep the final report concise and specific.
