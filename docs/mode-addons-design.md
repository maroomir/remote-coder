# Mode Addons — Design Decisions

Maintainer-facing rationale for the declarative mode addon system. The user-facing
how-to lives in [mode-addons.md](mode-addons.md) (and [mode-addons.ko.md](mode-addons.ko.md));
this file records **why** the design is shaped the way it is, not how to use it.

Feature in one line: drop `~/.remote-coder/addons/*.yaml` to add read-only prompt-preset
modes without code changes. Loaded once at boot — no hot reload.

## Decision 1: Keep `JobMode` StrEnum; do not retire it

`JobRequest.mode` was widened to `JobMode | str` instead of replacing the enum with a
plain string keyed off the registry.

Why: the builtin orchestration (most importantly the PLAN and AGENT_FIX flows) branches
on enum **identity** — `mode is JobMode.PLAN`, `mode is JobMode.AGENT_FIX` — across the
codebase. Because addon modes only ever flow through as `str`, they can never satisfy an
`is JobMode.*` check, so the builtin-only flows stay builtin-only by construction. Widening
the field rather than rewriting the enum preserves existing behavior with the smallest
possible change.

## Decision 2: `mode` validator normalizes builtins, preserves unknown strings

`JobRequest` uses a `mode="before"` validator (`_normalize_mode`):
- Builtin string values (`"plan"`, etc.) are coerced to the `JobMode` enum so the identity
  branches above keep firing.
- Unregistered strings are **not rejected** — they pass through unchanged.

Why pass-through instead of reject: backward compatibility with SQLite rows. An old row, or
a row written by an addon that has since been removed, must still deserialize. Validation of
addon names happens at registration (boot), not at every `JobRequest` construction.

## Decision 3: Single `ModeRegistry` seeded with builtins, then loaded with addons

`app/jobs/mode_registry.py` seeds the five builtins (`agent`, `plan`, `ask`, `research`,
`agent_fix`) as `ModeSpec`s and loads YAML addons into the **same** registry.
`get_mode_registry()` is an `lru_cache` process-wide singleton; `main.py` injects addons once
at boot via `load_addon_modes`.

Why one registry: the integration points (parser, command registry, `setMyCommands`,
update handler, natural-language flow, presenters, messages) were switched to read triggers,
slash names, prompts, and labels from this registry. That makes addon support **data-driven**
— a new YAML registers a trigger with zero code changes — and keeps builtins and addons on a
single source of truth so they cannot drift.

Note: addon prompt prefixes (`_PLAN_PROMPT` etc.) are kept byte-identical to the branches in
`app.ai.base.instruction_for_runner_mode`; a test asserts equality so the two copies cannot
silently diverge.

## Decision 4: Security invariants (the load-bearing part)

1. **Addons are read-only only.** `read_only` must be the boolean `true`; `false`, a missing
   field, or a non-bool truthy value is rejected. Write/commit/push capability stays
   builtin-exclusive — a dropped-in YAML can never grant write access.
2. **Prompt is text, not permission.** The `prompt` is just a prefix string. Capability is
   decided solely by the read-only flag, regardless of what the prompt text says.
3. **No trigger or name hijacking.** A `name` that collides with a builtin, violates
   `^[a-z][a-z0-9_]{1,30}$`, or whose slash/alias trigger shadows an existing trigger is
   rejected. The trigger index is rebuilt over the merged set *before* any state mutation, so a
   conflicting addon cannot overwrite a builtin keyword like `/plan`.
4. **`yaml.safe_load` only** — never `yaml.load`.
5. **One bad file never blocks boot.** Loading is per-file graceful skip; a parse error,
   validation failure, or unreadable file is logged with a short reason token only. Paths,
   tokens, and field values are kept out of the log message body.

`register_addon` re-checks the read-only invariant itself (not just `_build_addon_spec`), so
the guarantee holds no matter how a caller constructs the spec.

## Decision 5: Slash triggers use English slash names only; aliases are colon-prefix only

Slash triggers come from `slash_names()` plus the `fix` alias. Korean aliases (`/계획`, etc.)
are **not** slash triggers — they fire only via the colon prefix (`계획:`).

Why this is a regression trap: the parser and the command-registry passthrough must agree on
exactly which keywords are slash triggers. If aliases leak into the slash pattern, the two
trigger sets diverge and `/계획 <body>` is rejected as an Unknown command (this regression
actually happened once and was fixed). Concretely: `parser._build_slash_mode_pattern` uses
slash keywords only, `_build_prefix_mode_pattern` includes aliases; both are `lru_cache`d.

## Rejected alternatives

- **Replace `JobMode` with a registry-backed string** — rejected: forces touching ~18 builtin
  identity branches (esp. PLAN/AGENT_FIX orchestration) for no behavior gain and high
  regression risk. Widening the field is strictly smaller and safer (Decision 1).
- **Reject unknown mode strings in `JobRequest`** — rejected: breaks deserialization of old or
  removed-addon SQLite rows (Decision 2).
- **Hot reload of the addons directory** — rejected: out of scope; boot-time one-shot load
  keeps the registry immutable after startup and avoids mid-run trigger races.
- **Allow writable addons gated by a flag** — rejected: write/commit/push must stay
  builtin-exclusive so a dropped-in file can never escalate to write access (Decision 4).

## Verification baseline

Full suite passed (604 tests) at implementation time. Addon-specific coverage:
`tests/test_mode_registry.py`, `tests/test_addon_loading.py`, `tests/test_job_schemas.py`,
and the `tests/test_command_parser.py` slash/alias regression tests. Unrelated WIP
(diff-risk-summary test files) was out of scope for this work.
