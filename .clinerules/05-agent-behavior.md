# Agent Behavior Rules

These rules adapt the Karpathy-inspired coding-agent guidelines for `remote-coder`.

Source: https://github.com/forrestchang/andrej-karpathy-skills

Tradeoff: These guidelines bias toward caution over speed. For trivial tasks such as typo fixes or obvious one-line edits, use judgment.

## Think Before Coding

Do not assume silently, hide confusion, or skip tradeoffs.

Before implementing:

- State assumptions explicitly when they affect product behavior, architecture, security, or verification.
- Ask when an uncertainty could change the implementation.
- Present multiple plausible interpretations instead of silently choosing one.
- Say when a simpler approach exists, and push back when the requested path adds unnecessary complexity.
- If something is unclear, stop, name the confusion, and ask before editing.

## Simplicity First

Write the minimum code that solves the requested problem.

- Do not add features beyond what was asked.
- Do not add abstractions for single-use code.
- Do not add flexibility, configurability, or extension points that were not requested.
- Do not add defensive branches for scenarios that cannot happen in the current design.
- If a solution becomes much larger than the problem demands, simplify before finalizing.

Ask before finalizing: would a senior engineer say this is overcomplicated?

## Surgical Changes

Touch only what the request requires. Clean up only changes you introduce.

When editing existing code:

- Do not improve adjacent code, comments, formatting, or naming unless directly required.
- Do not refactor unrelated code.
- Match the existing style, even when you would choose a different style in new code.
- If you notice unrelated dead code or cleanup opportunities, mention them instead of changing them.

When your changes create unused imports, variables, functions, files, or tests, remove those orphans. Do not remove pre-existing dead code unless asked.

Every changed line should trace directly to the user's request.

## Goal-Driven Execution

Turn work into verifiable goals and loop until checked.

For non-trivial tasks, define success criteria before editing. Examples:

- "Add validation" becomes "cover invalid inputs, then make those checks pass."
- "Fix the bug" becomes "reproduce the bug, then verify the fix."
- "Refactor this module" becomes "preserve behavior before and after the refactor."

For multi-step tasks, state a brief plan in this shape:

```text
1. [Step] -> verify: [check]
2. [Step] -> verify: [check]
3. [Step] -> verify: [check]
```

Prefer project-defined verification commands. If automated verification is unavailable or not relevant, state the limitation and do focused manual inspection.

These rules are working when diffs stay focused, implementations stay small, and clarifying questions happen before mistaken implementation choices.
