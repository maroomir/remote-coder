from __future__ import annotations

from dataclasses import dataclass

from app.models import ModelName


@dataclass(frozen=True)
class ModelOption:
    label: str
    value: str


MODEL_CATALOG: dict[ModelName, tuple[ModelOption, ...]] = {
    ModelName.CLAUDE: (
        ModelOption("opus", "opus"),
        ModelOption("sonnet", "sonnet"),
        ModelOption("claude-opus-4-7", "claude-opus-4-7"),
        ModelOption("claude-sonnet-4-6", "claude-sonnet-4-6"),
    ),
    ModelName.CODEX: (
        ModelOption("gpt-5.3-codex", "gpt-5.3-codex"),
        ModelOption("gpt-5.5", "gpt-5.5"),
        ModelOption("gpt-5.4", "gpt-5.4"),
        ModelOption("gpt-5.4-mini", "gpt-5.4-mini"),
        ModelOption("gpt-5", "gpt-5"),
    ),
    ModelName.GEMINI: (
        ModelOption("auto", "auto"),
        ModelOption("gemini-3.1-pro-preview", "gemini-3.1-pro-preview"),
        ModelOption("gemini-3-pro-preview", "gemini-3-pro-preview"),
        ModelOption("gemini-3-flash-preview", "gemini-3-flash-preview"),
        ModelOption("gemini-2.5-pro", "gemini-2.5-pro"),
    ),
}


def get_model_options(provider: ModelName) -> tuple[ModelOption, ...]:
    return MODEL_CATALOG.get(provider, ())


def is_valid_model_id(provider: ModelName, model_id: str) -> bool:
    return any(option.value == model_id for option in get_model_options(provider))


def format_model_selection(provider: ModelName, model_id: str | None = None) -> str:
    return f"{provider.value} / {model_id}" if model_id else provider.value
