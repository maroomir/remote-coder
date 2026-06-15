from __future__ import annotations

import time

import httpx

from app.jobs.schemas import Job
from app.monitoring.events import EventLogger
from app.telegram.formatting import build_message_entities, prepare_outgoing
from app.telegram.i18n import language_from_settings_store, translate_button_label, translate_text
from app.telegram.messages import (
    OutboundButton as _OutboundButton,
    build_job_accepted_message,
    build_job_heartbeat_message,
    build_job_result_buttons,
    build_job_result_message,
)
from app.telegram.notifier_protocol import Notifier

_outbound = EventLogger("app.telegram.outbound", "telegram.outbound")

_VALID_BUTTON_STYLES = frozenset({"primary", "success", "danger"})


def _serialize_inline_button(btn, language) -> dict:
    payload: dict = {
        "text": translate_button_label(btn.label, language),
        "callback_data": btn.callback_data,
    }
    style = getattr(btn, "style", None)
    if style in _VALID_BUTTON_STYLES:
        payload["style"] = style
    return payload

class TelegramNotifier:
    _TELEGRAM_TEXT_LIMIT = 4096
    _MAX_ATTEMPTS = 3

    _CALLBACK_TOAST_LIMIT = 200

    def __init__(self, bot_token: str, advanced_settings_store=None) -> None:
        self._api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        self._edit_url = f"https://api.telegram.org/bot{bot_token}/editMessageText"
        self._callback_answer_url = f"https://api.telegram.org/bot{bot_token}/answerCallbackQuery"
        self._reaction_url = f"https://api.telegram.org/bot{bot_token}/setMessageReaction"
        self._advanced_settings_store = advanced_settings_store

    @property
    def _language(self):
        return language_from_settings_store(self._advanced_settings_store)

    @staticmethod
    def _extract_message_id(response: httpx.Response) -> int | None:
        try:
            data = response.json()
        except ValueError:
            return None
        result = data.get("result") if isinstance(data, dict) else None
        message_id = result.get("message_id") if isinstance(result, dict) else None
        return int(message_id) if message_id is not None else None

    def _post_with_retry(
        self,
        url: str,
        payload: dict,
        *,
        log_label: str,
        chat_id: int | None = None,
    ) -> httpx.Response | None:
        for attempt in range(1, self._MAX_ATTEMPTS + 1):
            try:
                response = httpx.post(url, json=payload, timeout=httpx.Timeout(10.0, connect=5.0))
                response.raise_for_status()
                return response
            except httpx.HTTPError as exc:
                _outbound.warning(
                    "%s attempt failed attempt=%d/%d err=%s",
                    log_label,
                    attempt,
                    self._MAX_ATTEMPTS,
                    type(exc).__name__,
                    chat_id=chat_id,
                )
                if attempt == self._MAX_ATTEMPTS:
                    _outbound.warning(
                        "%s failed after %d attempts: %s",
                        log_label,
                        self._MAX_ATTEMPTS,
                        type(exc).__name__,
                        chat_id=chat_id,
                    )
                    return None
                time.sleep(attempt)
        return None

    def _post_message(self, chat_id: int, text: str, *, with_entities: bool = True) -> int | None:
        if with_entities:
            out_text, entities = prepare_outgoing(text)
        else:
            out_text, entities = text, []
        _outbound.info("sendMessage start len=%d", len(out_text), chat_id=chat_id)
        payload: dict = {"chat_id": chat_id, "text": out_text}
        if entities:
            payload["entities"] = entities
        response = self._post_with_retry(
            self._api_url,
            payload,
            log_label="sendMessage",
            chat_id=chat_id,
        )
        if response is None:
            return None
        _outbound.info("sent text len=%d status=%d", len(out_text), response.status_code, chat_id=chat_id)
        return self._extract_message_id(response)

    def send_text(self, chat_id: int, text: str, *, skip_body_i18n: bool = False) -> int | None:
        out = text if skip_body_i18n else translate_text(text, self._language)
        return self._post_message(chat_id, out)

    def send_with_buttons(
        self,
        chat_id: int,
        text: str,
        inline_buttons: list,
        *,
        skip_body_i18n: bool = False,
    ) -> int | None:
        language = self._language
        out_text = text if skip_body_i18n else translate_text(text, language)
        out_text, entities = prepare_outgoing(out_text)
        keyboard = [
            [_serialize_inline_button(btn, language) for btn in row]
            for row in inline_buttons
        ]
        payload = {
            "chat_id": chat_id,
            "text": out_text,
            "reply_markup": {"inline_keyboard": keyboard},
        }
        if entities:
            payload["entities"] = entities
        button_count = sum(len(row) for row in inline_buttons)
        _outbound.info(
            "sendMessage buttons start len=%d rows=%d buttons=%d",
            len(out_text),
            len(inline_buttons),
            button_count,
            chat_id=chat_id,
        )
        response = self._post_with_retry(
            self._api_url,
            payload,
            log_label="sendMessage (buttons)",
            chat_id=chat_id,
        )
        if response is None:
            return None
        _outbound.info(
            "sent message with buttons len=%d status=%d",
            len(out_text),
            response.status_code,
            chat_id=chat_id,
        )
        return self._extract_message_id(response)

    def edit_message(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        inline_buttons: list,
        *,
        skip_body_i18n: bool = False,
    ) -> bool:
        language = self._language
        out_text = text if skip_body_i18n else translate_text(text, language)
        out_text, entities = prepare_outgoing(out_text)
        keyboard = [
            [_serialize_inline_button(btn, language) for btn in row]
            for row in inline_buttons
        ]
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": out_text,
            "reply_markup": {"inline_keyboard": keyboard},
        }
        if entities:
            payload["entities"] = entities
        _outbound.info(
            "editMessageText start len=%d rows=%d",
            len(out_text),
            len(inline_buttons),
            chat_id=chat_id,
        )
        return self._post_edit_with_retry(payload, chat_id=chat_id)

    def _post_edit_with_retry(self, payload: dict, *, chat_id: int) -> bool:
        for attempt in range(1, self._MAX_ATTEMPTS + 1):
            try:
                response = httpx.post(
                    self._edit_url, json=payload, timeout=httpx.Timeout(10.0, connect=5.0)
                )
                response.raise_for_status()
                _outbound.info("editMessageText ok status=%d", response.status_code, chat_id=chat_id)
                return True
            except httpx.HTTPStatusError as exc:
                description = self._error_description(exc.response)
                if "message is not modified" in description:
                    # The target already shows this exact text+markup; treat as success.
                    return True
                if (
                    "message to edit not found" in description
                    or "message can't be edited" in description
                    or "message_id_invalid" in description
                ):
                    _outbound.info(
                        "editMessageText not applicable (%s); caller falls back to send",
                        description or "unknown",
                        chat_id=chat_id,
                    )
                    return False
                _outbound.warning(
                    "editMessageText http error attempt=%d/%d status=%d",
                    attempt,
                    self._MAX_ATTEMPTS,
                    exc.response.status_code,
                    chat_id=chat_id,
                )
                return False
            except httpx.HTTPError as exc:
                _outbound.warning(
                    "editMessageText attempt failed attempt=%d/%d err=%s",
                    attempt,
                    self._MAX_ATTEMPTS,
                    type(exc).__name__,
                    chat_id=chat_id,
                )
                if attempt == self._MAX_ATTEMPTS:
                    return False
                time.sleep(attempt)
        return False

    @staticmethod
    def _error_description(response: httpx.Response) -> str:
        try:
            data = response.json()
        except ValueError:
            return ""
        description = data.get("description") if isinstance(data, dict) else None
        return description.lower() if isinstance(description, str) else ""

    def set_reaction(self, chat_id: int, message_id: int, emoji: str | None) -> bool:
        payload: dict = {
            "chat_id": chat_id,
            "message_id": message_id,
            "reaction": [{"type": "emoji", "emoji": emoji}] if emoji else [],
        }
        _outbound.info(
            "setMessageReaction emoji=%s",
            emoji or "(cleared)",
            chat_id=chat_id,
        )
        response = self._post_with_retry(
            self._reaction_url,
            payload,
            log_label="setMessageReaction",
            chat_id=chat_id,
        )
        return response is not None

    def answer_callback_query(
        self,
        callback_query_id: str,
        *,
        text: str | None = None,
        show_alert: bool = False,
    ) -> None:
        _outbound.info("answerCallbackQuery start")
        payload: dict = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = translate_text(text, self._language)[: self._CALLBACK_TOAST_LIMIT]
            if show_alert:
                payload["show_alert"] = True
        response = self._post_with_retry(
            self._callback_answer_url,
            payload,
            log_label="answerCallbackQuery",
        )
        if response is not None:
            _outbound.info("answerCallbackQuery sent status=%d", response.status_code)

    def send_job_accepted(self, job: Job) -> int | None:
        _outbound.info(
            "notify job accepted",
            chat_id=job.request.chat_id,
            job_id=job.id,
            project=job.request.project,
        )
        text, buttons = build_job_accepted_message(job)
        return self.send_with_buttons(job.request.chat_id, text, buttons)

    def send_job_result(self, job: Job) -> list[int]:
        _outbound.info(
            "notify job result status=%s changed_files=%d",
            job.status.value,
            len(job.changed_files),
            chat_id=job.request.chat_id,
            job_id=job.id,
            project=job.request.project,
        )
        text = build_job_result_message(job)
        buttons = build_job_result_buttons(job)
        accepted_message_id = job.accepted_message_id
        if accepted_message_id is not None:
            translated = translate_text(text, self._language)
            if len(translated) <= self._TELEGRAM_TEXT_LIMIT and self.edit_message(
                job.request.chat_id,
                accepted_message_id,
                translated,
                buttons,
                skip_body_i18n=True,
            ):
                return [accepted_message_id]
            # Edit-in-place failed or text is too long: drop the Stop button on the accepted
            # message so the multi-message result keeps reading cleanly.
            accepted_text, _ = build_job_accepted_message(job)
            self.edit_message(
                job.request.chat_id, accepted_message_id, accepted_text, []
            )
        return self.send_long_text(job.request.chat_id, text, buttons)

    def send_long_text(
        self,
        chat_id: int,
        text: str,
        inline_buttons: list | None = None,
        *,
        skip_body_i18n: bool = False,
    ) -> list[int]:
        """Split text across Telegram messages when it exceeds the 4096-character limit.

        When inline_buttons are given they are attached to the final chunk only, so a
        multi-part result still ends with a single actionable keyboard.
        """
        outgoing = text if skip_body_i18n else translate_text(text, self._language)
        chunks = self._chunk_text(outgoing, self._TELEGRAM_TEXT_LIMIT)
        _outbound.info(
            "send_long_text chunks=%d total_len=%d buttons=%s",
            len(chunks),
            len(outgoing),
            bool(inline_buttons),
            chat_id=chat_id,
        )
        message_ids: list[int] = []
        for idx, chunk in enumerate(chunks, 1):
            _outbound.info(
                "send_long_text chunk=%d/%d len=%d",
                idx,
                len(chunks),
                len(chunk),
                chat_id=chat_id,
            )
            if inline_buttons and idx == len(chunks):
                message_id = self.send_with_buttons(
                    chat_id, chunk, inline_buttons, skip_body_i18n=True
                )
            else:
                message_id = self._post_message(chat_id, chunk, with_entities=idx == 1)
            if message_id is not None:
                message_ids.append(message_id)
        return message_ids

    @staticmethod
    def _chunk_text(text: str, max_len: int) -> list[str]:
        if max_len <= 0:
            raise ValueError("max_len must be positive")
        if len(text) <= max_len:
            return [text]
        chunks: list[str] = []
        i = 0
        n = len(text)
        min_break = max_len // 2
        while i < n:
            j = min(i + max_len, n)
            if j < n:
                segment = text[i:j]
                cut = segment.rfind("\n")
                if cut >= min_break:
                    j = i + cut + 1
                else:
                    cut = segment.rfind(" ")
                    if cut >= min_break:
                        j = i + cut + 1
            chunks.append(text[i:j])
            i = j
        return chunks
