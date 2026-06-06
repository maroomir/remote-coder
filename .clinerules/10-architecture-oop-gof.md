# Architecture, OOP, and GoF Pattern Rules

## Core Development Principles

- Implement features in small, verifiable units.
- Separate external APIs, file system access, process execution, and Git operations behind service or adapter layers.
- Telegram webhook handlers must respond quickly; long-running AI work belongs in background jobs.
- Prefer safe isolation and clear observability over operational automation.
- In the MVP stage, prefer clear structure and testable code over premature abstraction.
- When requests are ambiguous, surface assumptions and tradeoffs before editing.
- Prefer the smallest change that satisfies the request.
- Do not add unrequested features, configuration, or extension points.
- Keep edits surgical. Do not clean up neighboring code, comments, or formatting unless directly required.
- Use object-oriented design as the default development style.
- Apply GoF patterns when they simplify the code or contain real variability. Do not add patterns for their own sake.

## OOP Rules

- Keep classes and modules close to single responsibility.
- Encapsulate Telegram API calls, Git operations, subprocess execution, and AI CLI details.
- Use interfaces or abstract base classes for replaceable components such as Claude/Codex/Gemini runners, job stores, and notifiers.
- Prefer composition over inheritance.
- Use domain names that reveal intent, such as `Job`, `JobManager`, `GitWorktreeService`, `AiRunner`, and `TelegramNotifier`.
- Keep functions and methods short enough to explain one behavior.

## Recommended Patterns

| Pattern | Candidate use |
|---|---|
| Strategy | Claude/Codex/Gemini runner selection, branch naming, worktree cleanup policy |
| Factory Method / Abstract Factory | Runner, store, notifier, or repository creation from configuration |
| Adapter | Telegram Bot API, Claude CLI, Codex CLI, Gemini CLI, Git CLI |
| Facade | Job execution flow through `JobManager` or `JobOrchestrator` |
| Template Method | Shared AI execution flow with tool-specific details |
| Command | Telegram command handling such as `/help`, `/model`, `/status` |
| Observer | Job state notifications, logs, and follow-up hooks |
| State | Explicit job state transitions when they become complex |
| Repository | Job storage and project configuration storage |

## Pattern Adoption Rules

- If branching keeps growing, consider Strategy, Command, or State.
- Wrap external tools and APIs with adapters so tests can mock them.
- Move complex creation logic behind a factory.
- Collapse long workflows behind a facade or orchestrator.
- Do not create multiple classes for simple or single-use behavior. Apply a pattern only when complexity or variation is real.

## Recommended Code Structure

```text
app/
  main.py                     # FastAPI application creation
  config.py                   # Environment and settings
  models.py                   # Shared models
  telegram/
    webhook.py                # Webhook router
    notifier.py               # Telegram message delivery
    commands/                 # /help, /model, /status, etc. (base, registry, one module per command group)
    parser.py                 # Message parsing
    conversation.py           # SQLite conversation context
    confirmations.py          # User confirmation flow
    model_preferences.py      # Model selection state
    project_preferences.py    # Project selection state
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
    base.py                   # AiRunner interface + BaseCliRunner shared run() skeleton
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
