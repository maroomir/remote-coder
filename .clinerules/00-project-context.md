# Project Context and Rule Structure

This file captures high-signal guidance for working on `remote-coder`.

## Project Identity

Remote AI Coder is a FastAPI-based automation system that uses Telegram as a remote interface for running local AI coding tools. It creates isolated Git worktrees, runs Claude Code, Codex CLI, or Gemini CLI, commits changes on a separate branch, and reports results back to Telegram.

Core flow:

```text
Telegram Message
  -> FastAPI Webhook
  -> Auth / Command Parser
  -> Job Manager
  -> Git Worktree
  -> AI Runner (Claude / Codex / Gemini)
  -> Git Commit
  -> Telegram Notification
```

## Current Source of Truth

- `PLAN.md` defines product goals, MVP scope, requirements, architecture, risks, and roadmap.
- `.clinerules/` defines Cline-readable development rules.
- `.cursor/rules/` defines Cursor-readable development rules with `.mdc` frontmatter.
- `AGENTS.md` defines AI-agent workflow, checklists, and final reporting expectations.
- `CLAUDE.md` is the Claude Code entry point and references the agent rule files.
- Existing source files and tests override intended architecture notes. If implementation and documentation disagree, investigate before editing.

## Rule File Roles

| Document | Role | Update when |
|---|---|---|
| `PLAN.md` | Product plan, MVP scope, requirements, roadmap | Product scope, requirements, architecture, or roadmap changes |
| `.clinerules/` | Project-wide development rules for Cline | Development principles, security rules, structure, or test policy changes |
| `.cursor/rules/` | Cursor-compatible mirror of project rules | The matching Cline rules change |
| `AGENTS.md` | AI-agent operating manual | Agent workflow, checklists, or reporting rules change |
| `CLAUDE.md` | Claude Code context entry point | Rule file list or Claude-specific context changes |

Keep Cline and Cursor rules aligned in intent. The syntax and file format differ; the policy should not.

## Priority Order

Before non-trivial work, consult sources in this order:

1. The user's latest explicit instruction.
2. `PLAN.md`.
3. `.clinerules/`.
4. `.cursor/rules/`.
5. `AGENTS.md`.
6. Existing code and tests.

If documents conflict in a way that could change behavior, ask the user before editing. Clear typos or stale wording can be fixed while preserving intent.

## MVP Implementation Priority

1. FastAPI application skeleton.
2. Environment/configuration loading.
3. Telegram webhook receiving.
4. Chat/User allowlist authentication.
5. Job model and state management.
6. Git worktree service.
7. Claude Runner.
8. Telegram result notifications.
9. Codex Runner.
10. Gemini Runner.
11. Tests and documentation cleanup.

## When to Update Rules

Suggest rule updates when:

- The user corrects an assumption about architecture, workflow, or security.
- A change requires touching files that were not obvious from the request.
- A non-obvious convention is discovered after investigation.
- A repeated mistake could be prevented by documenting a rule.
- The user explicitly asks to add or synchronize agent instructions.

Avoid adding generic programming advice that can be inferred from normal Python, FastAPI, or Git practices.
