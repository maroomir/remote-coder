# AGENTS.md

AI-agent workflow for `remote-coder`. Domain rules live in `.cursor/rules/`; product scope in `PLAN.md`.

## Project Identity

FastAPI service that lets allowed Telegram users run local AI coding tools and Ollama local models remotely. Each registered project has its own bot token and allowlist. Webhook path: `/telegram/webhook/{sha256_prefix16}` (first 16 hex chars of SHA-256(bot token), not the raw token). **Bot instance = project context** — commands, confirmations, model prefs, and jobs are scoped to that project.

```text
Telegram Message -> Webhook -> BotInstanceManager -> Parser -> JobManager -> Git Worktree -> AI Runner -> Git Commit -> Telegram Notification
```

## Source of Truth

1. The user's latest explicit instruction.
2. `PLAN.md`.
3. `.cursor/rules/`.
4. `AGENTS.md`.
5. Existing code and tests.

If documents conflict in a way that could change behavior, ask before editing.

## Pre-Work Checklist

- [ ] Task is inside `PLAN.md` scope?
- [ ] Assumptions, tradeoffs, and success criteria are clear?
- [ ] Change respects `.cursor/rules/`?
- [ ] Secrets, Git mutation, subprocess, or risky ops identified?
- [ ] Worktree/branch policy preserved?
- [ ] Tests or docs needed?
- [ ] Rule doc updates needed?

## Post-Work Checklist

- [ ] Request satisfied; tests added/updated when needed.
- [ ] Verification run, or limitation stated.
- [ ] No unrelated refactors or cleanup mixed in.
- [ ] New env vars, commands, or config documented in README.
- [ ] Rule or roadmap changes reflected in the right docs.

## Verification

```bash
conda run -n remote-coder pytest -q
```

Full pass (CI-style):

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 conda run -n remote-coder pytest -q -p pytest_asyncio.plugin -p respx.fixtures
```

Run focused tests first for narrow changes. Mock Telegram API, AI CLI, real Git repos, and external networks in unit tests.

## Commit Message Style

Write all commit messages in English. Use this format:

```text
type: Title

- Body sentence.
- Body sentence.
```

- Subject format is `type: title`.
- Subject must be 50 characters or less.
- Subject must clearly describe what changed.
- Do not end the subject with a period.
- Keep one blank line between the subject and body.
- Start each body line with `-`.
- Write each body bullet as a complete sentence, preferably 100 characters or less.

Allowed types:

- `feat`: new feature.
- `fix`: bug fix.
- `docs`: documentation change.
- `test`: test code addition or update.
- `refact`: code refactoring.
- `style`: change that does not affect code meaning.
- `chore`: build or package manager change.

## Release Preparation

When the user asks to prepare a release or bump the version:

1. Follow `RELEASE.md` end-to-end.
2. Update `CHANGELOG.md` (`[Unreleased]`) and `CHANGELOG.ko.md` (`[미배포]`): add `## [X.Y.Z] — YYYY-MM-DD`, move unreleased items.
3. Keep the version bump commit minimal: `pyproject.toml`, `app/__init__.py`, `tests/test_cli.py`, `CHANGELOG.md`, `CHANGELOG.ko.md`.
4. Version bump commit message: `chore: bump version to vX.Y.Z`.
5. `git push` and annotated tags only when the user explicitly requests or confirms `RELEASE.md` push steps.

## Rule Synchronization

Update `.cursor/rules/` when changing security policy, Git/worktree policy, AI runner behavior, Telegram commands, testing strategy, or comment policy. Update `AGENTS.md` when agent workflow or reporting changes. Update `CLAUDE.md` only when the rule index changes. Update `PLAN.md` for product/roadmap changes.

## Final Report Format

When work is complete, summarize:

- Changed files.
- Implemented behavior or written documentation.
- Security/configuration notes.
- Verification commands and results, or why verification was limited.
- Whether rule documents were updated.
- Remaining TODOs or follow-up work.

Keep the final report concise and specific.
