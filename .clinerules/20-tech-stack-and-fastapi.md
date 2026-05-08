# Tech Stack and FastAPI Rules

## Recommended Stack

- Python 3.11 or newer.
- FastAPI.
- Uvicorn.
- pytest.
- `python-dotenv` or `pydantic-settings`.
- `pyproject.toml` based packaging.
- Telegram Bot API calls through a small adapter or a stable Telegram library.
- Git CLI based worktree management.
- Claude Code CLI, Codex CLI, and Gemini CLI adapters.

## FastAPI Rules

- Webhook endpoints must respond quickly.
- Long-running AI jobs must run in the background job flow, not inside the webhook request.
- Separate routers, services, settings, and models.
- Use Pydantic models for request validation.
- Do not execute AI CLI work directly inside webhook request handling.

## Configuration Rules

- Centralize environment variables in `config.py` or a settings object.
- Support project-specific settings through YAML/JSON configuration when needed.
- Use safe defaults.
- Document new environment variables in `.env.example` and README.
- Before running tests or the server, use the `remote-coder` Conda environment.
- If activation is difficult in an automated context, use `conda run -n remote-coder ...`.

## Packaging Rules

- Before public release, use `0.0.1` as the initial package version.
- Provide a `remote-coder` console script for installable execution.
- Prefer a Homebrew Formula over a Cask for CLI/server distribution.
