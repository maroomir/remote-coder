@.cursor/rules/00-project-context.mdc
@.cursor/rules/05-agent-behavior.mdc
@.cursor/rules/10-architecture-oop-gof.mdc
@.cursor/rules/15-clean-code.mdc
@.cursor/rules/20-tech-stack-and-fastapi.mdc
@.cursor/rules/30-security-telegram.mdc
@.cursor/rules/40-git-job-ai-runner.mdc
@.cursor/rules/50-testing-docs-sync.mdc
@.cursor/rules/60-comments-policy.mdc

Persistent project rules: `.cursor/rules/`. Agent workflow: `AGENTS.md`. Product scope: `PLAN.md`.

Multi-bot: each registered project uses its own bot; webhook paths use the first 16 hex chars of SHA-256(bot token). See `docs/multi-bot-setup.md`.

Release/version bumps: `RELEASE.md`, `CHANGELOG.md`, `CHANGELOG.ko.md`, and the Release preparation section in `AGENTS.md`.

## Commit message style

Write every commit as `<type>: <title>`, then a blank line, then a `-` bulleted body. Everything in English.

- Title: `<type>: <title>` on the first line — say *what* changed, ≤ 50 chars, no trailing period (e.g. `feat: Add login feature`).
- Keep the blank line between title and body; it separates them.
- Body: one `-` per change, each a complete sentence on a single line with no wrapping (≤ 100 chars recommended).
- Types: `feat` (new feature), `fix` (bug fix), `docs` (documentation), `test` (test code), `refact` (refactor), `style` (no behavior change), `chore` (build/tooling/deps).
- Do not append a `Co-Authored-By` trailer.
