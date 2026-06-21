# Declarative Mode Addons

*English: this document · 한국어: [mode-addons.ko.md](mode-addons.ko.md)*

Remote AI Coder ships five **builtin modes** (`agent`, `plan`, `ask`, `research`, and the fix flow). You can add your own **read-only prompt-preset modes** without changing any code: drop a YAML file under the addons directory and restart the server. Each addon registers a new trigger (slash command and optional natural-language prefix) that runs the selected AI CLI with a fixed prompt prefix in a detached worktree.

Addons are **read-only only**. Write, commit, and push capability stays builtin-exclusive, so a dropped-in YAML can never grant write access.

## Where YAML Files Go

One YAML file equals one mode. Place files here:

```text
~/.remote-coder/addons/*.yaml
```

The directory lives under `REMOTE_CODER_HOME` (defaults to `~/.remote-coder`). If the directory does not exist, no addons load and the builtin modes are unaffected.

Addons load **once at server boot**. There is no hot reload — after adding, editing, or removing a file, restart the server for the change to take effect.

## YAML Schema

The file is a single top-level mapping with these fields:

| Field | Required | Type | Description |
|---|---|---|---|
| `name` | Yes | string | Mode identifier. Must match `^[a-z][a-z0-9_]{1,30}$` (starts with a lowercase letter; lowercase letters, digits, and underscores; 2–31 characters). Drives the `/name` slash command. |
| `read_only` | Yes | boolean | Must be `true`. Any other value (including `false`, `1`, or `"true"`) makes the file rejected. |
| `prompt` | Yes | string | Prefix text prepended to the user instruction. May contain line breaks. |
| `slash` | No | boolean | Defaults to `true`. When `true`, the mode triggers via the `/name` slash command. |
| `aliases` | No | list of strings | Natural-language prefix aliases (for example a Korean word). Each alias triggers only via the colon prefix `alias: instruction`. |
| `help` | No | map (lang → string) | Help text. If present, the `en` key is required. Used as the slash autocomplete description. |
| `label` | No | map (lang → string) | Display label. Falls back to `name` when omitted. |

Notes:

- The `prompt` text does not affect permissions. Even if it says "edit files" or "push to remote", only the `read_only` flag decides capability, and addon modes are always read-only.
- `name` must not collide with a builtin name (`agent`, `plan`, `ask`, `research`, `agent_fix`).
- No trigger may collide with an existing one. Builtin slash names and aliases (`plan`, `ask`, `research`, `계획`, `질문`, `조사`, `fix`, `수정`) are already taken, and addons cannot shadow them.
- YAML parses `yes`/`on` as boolean `true`, so they are accepted for `read_only`, but `true` is recommended for clarity.

## Complete Example

`~/.remote-coder/addons/review.yaml`:

```yaml
name: review
read_only: true
prompt: |
  You are in REVIEW mode. Read the code and report issues:
  correctness, security, readability, and tests.
  Do not modify files.
slash: true
aliases:
  - 리뷰
help:
  en: "Review the code and report issues"
  ko: "코드를 검토하고 문제를 보고"
label:
  en: "Review"
  ko: "리뷰"
```

After a server restart, this registers a `review` mode and adds `/review` to the Telegram slash autocomplete menu (`setMyCommands`).

## Triggering A Mode

Using the `review` example above, three forms work, matching the builtin read-only modes:

- **Slash command with instruction**: `/review check the login flow for issues`
- **Natural-language alias prefix**: `리뷰: check the login flow for issues`
- **Bare slash command**: send `/review` alone, and the next message you send becomes the instruction.

The slash command uses the English `name` only; aliases trigger only through the colon prefix (`alias: instruction`), never as `/alias`.

## Security Constraints

- **Read-only only**: addon modes always run in a detached worktree with no commit and no push. `read_only: true` is mandatory; any writable spec is rejected. Write/commit/push modes stay builtin-exclusive.
- **Prompt text is not a permission**: wording in `prompt` never grants write access. Capability is decided solely by the read-only invariant.

## Invalid Files Are Skipped

If a file fails validation — bad `name` or schema, `read_only` not `true`, a builtin or trigger conflict, a missing required field, a YAML parse error, or an unreadable file — it is **skipped with a warning log** and does not affect other valid addons or server startup (per-file graceful skip). The warning log records only a short reason token; the file path and contents are not logged.
