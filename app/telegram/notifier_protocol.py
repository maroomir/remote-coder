from __future__ import annotations

from typing import Protocol

from app.jobs.schemas import Job


class Notifier(Protocol):
    def send_text(self, chat_id: int, text: str, *, skip_body_i18n: bool = False) -> int | None: ...

    def send_with_buttons(
        self,
        chat_id: int,
        text: str,
        inline_buttons: list,
        *,
        skip_body_i18n: bool = False,
    ) -> int | None: ...

    def edit_message(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        inline_buttons: list,
        *,
        skip_body_i18n: bool = False,
    ) -> bool: ...

    def answer_callback_query(
        self,
        callback_query_id: str,
        *,
        text: str | None = None,
        show_alert: bool = False,
    ) -> None: ...

    def send_job_accepted(self, job: Job) -> int | None: ...

    def send_job_result(self, job: Job) -> list[int]: ...

    def send_long_text(self, chat_id: int, text: str, inline_buttons: list | None = None) -> list[int]: ...
