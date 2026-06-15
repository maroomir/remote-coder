from fastapi import BackgroundTasks

from app.telegram.commands import CommandResponse, TelegramMessage
from app.telegram.handlers.command_flow import CommandFlow
from app.telegram.handlers.request import (
    TelegramChat,
    TelegramIncomingMessage,
    TelegramUpdate,
    WebhookRequest,
)


class _Registry:
    def __init__(self, response: CommandResponse | None) -> None:
        self.response = response

    def dispatch_rich(self, message, ctx):
        return self.response


class _Notifier:
    def __init__(self) -> None:
        self.sent_text: list[tuple[int, str, bool]] = []
        self.sent_long: list[tuple[int, str, bool]] = []

    def send_text(self, chat_id: int, text: str, *, skip_body_i18n: bool = False):
        self.sent_text.append((chat_id, text, skip_body_i18n))
        return 1

    def send_long_text(
        self,
        chat_id: int,
        text: str,
        inline_buttons=None,
        *,
        skip_body_i18n: bool = False,
    ):
        self.sent_long.append((chat_id, text, skip_body_i18n))
        return [1]


def _request(notifier: _Notifier, background_tasks: BackgroundTasks) -> WebhookRequest:
    message = TelegramMessage(chat_id=123, user_id=456, text="/log job_1")
    return WebhookRequest(
        update=TelegramUpdate(
            update_id=1,
            message=TelegramIncomingMessage(
                message_id=10,
                text=message.text,
                chat=TelegramChat(id=message.chat_id),
                from_user={"id": message.user_id},
            ),
        ),
        background_tasks=background_tasks,
        notifier=notifier,
        command_context=None,
        scope_project="remote-coder",
        chat_id=message.chat_id,
        user_id=message.user_id,
        message=message,
        message_head_lower="/log",
        reply_mid=None,
        reply_txt=None,
    )


def test_command_flow_uses_long_text_for_plain_command_response():
    notifier = _Notifier()
    background_tasks = BackgroundTasks()
    flow = CommandFlow(
        command_registry=_Registry(
            CommandResponse("A" * 5000, skip_notifier_body_i18n=True)
        )
    )

    result = flow.handle_command(_request(notifier, background_tasks))

    assert result == {"status": "ok"}
    assert len(background_tasks.tasks) == 1
    task = background_tasks.tasks[0]
    task.func(*task.args, **task.kwargs)
    assert notifier.sent_text == []
    assert notifier.sent_long == [(123, "A" * 5000, True)]
