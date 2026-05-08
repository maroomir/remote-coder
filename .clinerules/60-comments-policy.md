# Comments Policy

Applies to Python source, tests, and project scripts unless a task says otherwise.

## Project Preference: Minimal Comments

- Default to adding no new comments.
- Keep comments only for information the code cannot express.
- Prefer clearer names, types, and structure over explanatory comments.
- Do not add decorative section comments, narration, or docstrings that repeat signatures.
- When unsure, leave the comment out.

## When to Add a Comment

Add a comment only when skipping it would likely mislead someone or hide a real constraint:

- **Why / non-obvious constraint**: external API, OS, or library limitation.
- **Security / operations warning**: production impact, permission bypass, dangerous option, trust boundary.
- **Domain rule**: product, policy, or external specification that is not obvious from code.
- **Performance / correctness tradeoff**: an intentional choice future readers might otherwise "fix."
- **Workaround**: include an issue/PR reference and the condition for removal.

Prefer one tagged line when possible.

## Allowed Markers

Use only these markers:

| Marker | Use |
|---|---|
| `TODO(<issue>):` | Planned work with a tracking issue |
| `FIXME(<issue>):` | Known bug or incorrect behavior with a tracking issue |
| `NOTE:` | Non-obvious contract, coupling, or "not a bug" context |
| `SECURITY:` | Security assumption, trust boundary, or forbidden behavior |

Do not use untracked `TODO` or `FIXME`. Do not use vague markers such as `HACK` or `XXX`.

## Do Not Add

- Comments that restate implementation, such as `# Increment counter` or `# Return result`.
- Docstrings that repeat function/class signatures.
- Commented-out old code blocks. Git history is enough.
- Decorative separators or chatty commentary.

## Docstring Rules

- Remove obvious one-line docstrings.
- Use docstrings only for domain rules, constraints, tradeoffs, or complex public facades.
- Do not add docstrings to `__init__.py`, simple dataclasses, or DTO modules.
- Public library-style APIs may use short English docstrings when they do not duplicate the signature.

## Language

- Prefer English for new code comments and docstrings.
- Preserve existing Korean comments unless editing them is directly required.

## Review Checklist

When adding or reviewing comments, verify:

- Could the comment be replaced by a better name, type, or structure?
- Will it explain why this exists to someone reading the code six months later?
- If it uses `TODO` or `FIXME`, does it include a tracking issue?
