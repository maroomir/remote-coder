# AI Runner Guide

*English: this document · 한국어: [ai-runners.ko.md](ai-runners.ko.md)*

Remote AI Coder runs Claude Code, Codex CLI, Gemini CLI, and Ollama through the same Job flow. Whichever model you use, the tool must be installed, authenticated when needed, and available to the **same OS user account** that runs the server.

## Common Checks

1. Run `remote-coder doctor` to check local tool availability.
2. Smoke-test the CLI directly before using it through Telegram.
3. Select the default model with `/model`, or pass `model: claude`, `model: codex`, `model: gemini`, or `model: ollama` in a request.
4. When a Job fails, inspect the raw log at `~/.remote-coder/worktrees/<project>/_logs/<job_id>.log` instead of relying only on the Telegram summary.

Model selection priority:

1. `model: ...` in the natural-language request
2. The current chat's `/model` setting
3. The project's `default_model` in the registry

## Claude Code

Check installation:

```bash
command -v claude
```

Login and smoke-test:

```bash
claude
cd /tmp
claude -p "Say hello in one line" --dangerously-skip-permissions
```

Use with Remote AI Coder:

```text
/model claude
Make the README copy more concise
```

Notes:

- If you see `Not logged in · Please run /login`, run `claude` and log in as the server user.
- The Claude runner uses `--dangerously-skip-permissions` for non-interactive execution. Keep Telegram allowlists and project path restrictions in place.

## Codex CLI

Check installation:

```bash
command -v codex
```

Smoke-test:

```bash
cd /tmp
codex exec "print a one line greeting"
```

To test file edits, run Codex in a writable sandbox inside a test repository.

```bash
cd /path/to/your/git/repo
codex exec --sandbox workspace-write "Add one test line to README and explain what changed"
```

Use with Remote AI Coder:

```text
/model codex
model: codex Make the README copy more concise
```

Notes:

- Codex CLI can behave close to read-only in non-interactive mode.
- Remote AI Coder passes `--sandbox workspace-write` by default.
- You can choose `read-only`, `workspace-write`, or `danger-full-access` through `CODEX_SANDBOX` or the admin UI's `codex_sandbox` setting. Use `danger-full-access` only in trusted environments.

## Gemini CLI

Check installation:

```bash
command -v gemini
```

Install it if needed:

```bash
npm install -g @google/gemini-cli
```

Authenticate and smoke-test:

```bash
gemini
cd /tmp
gemini --approval-mode yolo -p "Say hello in one line"
```

Use with Remote AI Coder:

```text
/model gemini
model: gemini Make the README copy more concise
```

Notes:

- Gemini authentication must be completed as the server user.
- `--approval-mode yolo` is a risky option that allows non-interactive changes. Use it only with project restrictions, Telegram allowlists, and Job worktree isolation in place.
- For authentication, quota, and model-access issues, start from the Gemini CLI error message.

## Ollama

Check installation and the local daemon:

```bash
command -v ollama
ollama serve
ollama list
```

Install a model if needed:

```bash
ollama pull qwen2.5-coder:7b
```

Use with Remote AI Coder:

```text
/model ollama
/model ollama qwen2.5-coder:7b
ask: model: ollama explain the job execution pipeline
```

Notes:

- `/model ollama` queries the local Ollama server and lists models returned by `/api/tags`.
- If no specific model is selected, the runner uses `REMOTE_CODER_OLLAMA_DEFAULT_MODEL` or the first local model from Ollama.
- Reply-linked Ollama jobs store local transcripts in `~/.remote-coder/ollama_sessions/` and replay recent messages for continuity.
- PLAN, ASK, and RESEARCH run as read-only prompts. AGENT and FIX are best-effort: the adapter asks the model for fenced unified diff blocks and applies valid patches with `git apply`.
- Ollama does not provide provider quota. `/monitor model` shows local model availability and token counts recorded from Ollama responses.

## Troubleshooting

### CLI Command Not Found

- Check `command -v claude`, `command -v codex`, `command -v gemini`, and `command -v ollama` as the server user.
- Make sure shell startup files, `PATH`, and package install locations are visible to the service environment.

### Telegram Job Fails In The Runner Stage

- First, run the CLI smoke test as the same user account.
- Inspect stdout/stderr in `~/.remote-coder/worktrees/<project>/_logs/<job_id>.log`.
- Check authentication expiry, quota, sandbox mode, and permission options first.

### Worktree Fails As Read-Only

- Separate OS filesystem permissions from CLI sandbox behavior.
- For a step-by-step checklist, see the [read-only worktree guide](read-only-workspace.md).
