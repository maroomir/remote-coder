from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.ai.model_catalog import format_model_selection
from app.ai.usage import format_token_usage
from app.jobs.schemas import Job, JobMode
from app.monitoring.events import EventLogger
from app.telegram.i18n import language_from_settings_store, translate_button_label, translate_text

_outbound = EventLogger("app.telegram.outbound", "telegram.outbound")


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

    def answer_callback_query(self, callback_query_id: str) -> None: ...

    def send_job_accepted(self, job: Job) -> int | None: ...

    def send_job_result(self, job: Job) -> list[int]: ...

    def send_long_text(self, chat_id: int, text: str) -> list[int]: ...


@dataclass
class _OutboundButton:
    label: str
    callback_data: str


def build_job_accepted_message(job: Job) -> tuple[str, list[list[_OutboundButton]]]:
    lines = [
        "✅ Job accepted",
        "",
        f"- Job ID: {job.id}",
        f"- Project: {job.request.project}",
        f"- Model: {format_model_selection(job.request.model, job.request.model_id)}",
    ]
    if job.request.mode is JobMode.PLAN:
        lines.append("- Mode: plan")
    elif job.request.mode is JobMode.ASK:
        lines.append("- Mode: ask")
    buttons = [[_OutboundButton("Stop job", f"/stop {job.id}")]]
    return "\n".join(lines), buttons


def build_job_result_message(job: Job) -> str:
    mode_prefix = ""
    if job.request.mode is JobMode.PLAN:
        mode_prefix = "[plan] "
    elif job.request.mode is JobMode.ASK:
        mode_prefix = "[ask] "

    if job.status.value == "cancelled":
        return (
            f"{mode_prefix}⛔ Job cancelled\n\n"
            f"- Job ID: {job.id}\n"
            f"- Project: {job.request.project}"
        )

    if job.status.value == "succeeded":
        if job.request.mode in (JobMode.PLAN, JobMode.ASK):
            label = "plan" if job.request.mode is JobMode.PLAN else "ask"
            model_label = job.runner_actual_model or format_model_selection(
                job.request.model,
                job.request.model_id,
            )
            text = (
                f"[{label}] Completed\n\n"
                f"- Job ID: {job.id}\n"
                f"- Project: {job.request.project}\n"
                f"- Model used: {model_label}\n"
                f"- Token usage: {format_token_usage(job.runner_token_usage) or 'unavailable'}"
            )
            if job.runner_stdout_summary:
                text += f"\n\nAI response:\n{job.runner_stdout_summary}"
            return text

        changed = ", ".join(job.changed_files) if job.changed_files else "No changes"
        branch_line = job.branch if job.branch else "(none - no branch; no changes)"
        commit_line = job.commit_hash or "-"
        if job.changed_files and not job.request.commit:
            commit_line = "(no commit - commit/push skipped)"
        elif job.changed_files and job.request.commit and not job.commit_hash:
            commit_line = "(nothing staged - push skipped)"
        model_label = job.runner_actual_model or format_model_selection(
            job.request.model,
            job.request.model_id,
        )
        text = (
            f"✅ Job completed\n\n"
            f"- Job ID: {job.id}\n"
            f"- Project: {job.request.project}\n"
            f"- Branch: {branch_line}\n"
            f"- Commit: {commit_line}\n"
            f"- Changed files: {changed}\n"
            f"- Model used: {model_label}\n"
            f"- Token usage: {format_token_usage(job.runner_token_usage) or 'unavailable'}"
        )
        if job.runner_stdout_summary:
            text += f"\n\nAI response:\n{job.runner_stdout_summary}"
        return text

    details = []
    if job.error_stage:
        details.append(f"- Failure stage: {job.error_stage}")
    if job.log_path:
        details.append(f"- Log path: {job.log_path}")
    text = (
        f"{mode_prefix}❌ Job failed\n\n"
        f"- Job ID: {job.id}\n"
        f"- Project: {job.request.project}\n"
        f"- Error: {job.error or 'unknown error'}"
    )
    if details:
        text += "\n" + "\n".join(details)
    failure_summary = job.runner_stderr_summary or job.runner_stdout_summary
    if failure_summary:
        text += f"\n\nFailure output summary:\n{failure_summary}"
    return text


class TelegramNotifier:
    _TELEGRAM_TEXT_LIMIT = 4096
    _MAX_ATTEMPTS = 3

    def __init__(self, bot_token: str, advanced_settings_store=None) -> None:
        self._api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        self._callback_answer_url = f"https://api.telegram.org/bot{bot_token}/answerCallbackQuery"
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

    def _post_message(self, chat_id: int, text: str) -> int | None:
        _outbound.info("sendMessage start len=%d", len(text), chat_id=chat_id)
        response = self._post_with_retry(
            self._api_url,
            {"chat_id": chat_id, "text": text},
            log_label="sendMessage",
            chat_id=chat_id,
        )
        if response is None:
            return None
        _outbound.info("sent text len=%d status=%d", len(text), response.status_code, chat_id=chat_id)
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
        keyboard = [
            [
                {"text": translate_button_label(btn.label, language), "callback_data": btn.callback_data}
                for btn in row
            ]
            for row in inline_buttons
        ]
        payload = {
            "chat_id": chat_id,
            "text": out_text,
            "reply_markup": {"inline_keyboard": keyboard},
        }
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

    def answer_callback_query(self, callback_query_id: str) -> None:
        _outbound.info("answerCallbackQuery start")
        response = self._post_with_retry(
            self._callback_answer_url,
            {"callback_query_id": callback_query_id},
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
        return self.send_long_text(job.request.chat_id, build_job_result_message(job))

    def send_long_text(self, chat_id: int, text: str) -> list[int]:
        """Split text across Telegram messages when it exceeds the 4096-character limit."""
        outgoing = translate_text(text, self._language)
        chunks = self._chunk_text(outgoing, self._TELEGRAM_TEXT_LIMIT)
        _outbound.info(
            "send_long_text chunks=%d total_len=%d",
            len(chunks),
            len(outgoing),
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
            message_id = self._post_message(chat_id, chunk)
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
