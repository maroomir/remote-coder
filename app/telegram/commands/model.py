from __future__ import annotations

from app.ai.model_catalog import format_model_selection, get_model_options, is_valid_model_id
from app.models import ModelName
from app.telegram.commands.base import (
    MODEL_USAGE,
    CommandContext,
    InlineButton,
    TelegramCommand,
    TelegramMessage,
    _button_rows,
    effective_model_selection_for_chat,
    effective_project_name_for_chat,
    format_usage,
)
from app.telegram.model_preferences import ModelPreference


class ModelCommand(TelegramCommand):
    name = "/model"
    menu_text = "모델을 선택하세요."
    description = "채팅의 기본 AI 모델을 확인하거나 변경합니다"

    def execute(self, message: TelegramMessage, ctx: CommandContext) -> str:
        tokens = message.text.strip().split()
        project_name = effective_project_name_for_chat(ctx, message.chat_id)
        current = effective_model_selection_for_chat(ctx, message.chat_id, project_name)
        if len(tokens) == 1:
            return (
                "모델 설정\n\n"
                f"- 현재 기본 모델: {format_model_selection(current.provider, current.model_id)}"
            )
        if len(tokens) == 2 and tokens[1] in {model.value for model in ModelName}:
            selected = ModelName(tokens[1])
            ctx.model_preferences.set(project_name, message.chat_id, selected)
            return "\n".join(
                [
                    "모델 Provider가 선택되었습니다.",
                    "",
                    f"- 기본 모델: {selected.value}",
                    "- 세부 Model을 선택하세요.",
                ]
            )
        if len(tokens) == 3 and tokens[1] in {model.value for model in ModelName}:
            selected = ModelName(tokens[1])
            model_id = tokens[2]
            if not is_valid_model_id(selected, model_id):
                return f"알 수 없는 세부 Model입니다: {model_id}\n\n" + format_usage(
                    "/model",
                    f"/model {MODEL_USAGE}",
                    f"/model {MODEL_USAGE} <model_id>",
                )
            ctx.model_preferences.set_selection(
                project_name,
                message.chat_id,
                ModelPreference(selected, model_id),
            )
            return (
                "모델 설정이 변경되었습니다.\n\n"
                f"- 기본 모델: {format_model_selection(selected, model_id)}"
            )
        return format_usage("/model", f"/model {MODEL_USAGE}", f"/model {MODEL_USAGE} <model_id>")

    def get_inline_buttons(
        self,
        message: TelegramMessage | None = None,
        ctx: CommandContext | None = None,
    ) -> list[list[InlineButton]] | None:
        tokens = message.text.strip().split() if message is not None else []
        if len(tokens) <= 1:
            return [
                [
                    InlineButton("claude", "/model claude"),
                    InlineButton("codex", "/model codex"),
                    InlineButton("gemini", "/model gemini"),
                ]
            ]
        if len(tokens) == 2 and tokens[1] in {model.value for model in ModelName}:
            provider = ModelName(tokens[1])
            return _button_rows(
                [
                    InlineButton(option.label, f"/model {provider.value} {option.value}")
                    for option in get_model_options(provider)
                ],
                per_row=1,
            )
        return None
