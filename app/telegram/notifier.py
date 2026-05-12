from __future__ import annotations

import time

import httpx

from app.ai.usage import format_token_usage
from app.jobs.schemas import Job, JobMode
from app.monitoring.events import EventLogger

_outbound = EventLogger("app.telegram.outbound", "telegram.outbound")


class TelegramNotifier:
    _TELEGRAM_TEXT_LIMIT = 4096

    def __init__(self, bot_token: str) -> None:
        self._api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        self._callback_answer_url = f"https://api.telegram.org/bot{bot_token}/answerCallbackQuery"

    def send_text(self, chat_id: int, text: str) -> None:
        payload = {"chat_id": chat_id, "text": text}
        max_attempts = 3
        _outbound.info("sendMessage start len=%d", len(text), chat_id=chat_id)
        for attempt in range(1, max_attempts + 1):
            try:
                response = httpx.post(
                    self._api_url,
                    json=payload,
                    timeout=httpx.Timeout(10.0, connect=5.0),
                )
                response.raise_for_status()
                _outbound.info(
                    "sent text len=%d attempt=%d status=%d",
                    len(text),
                    attempt,
                    response.status_code,
                    chat_id=chat_id,
                )
                return
            except httpx.HTTPError as exc:
                _outbound.warning(
                    "sendMessage attempt failed attempt=%d/%d err=%s",
                    attempt,
                    max_attempts,
                    type(exc).__name__,
                    chat_id=chat_id,
                )
                if attempt == max_attempts:
                    _outbound.warning(
                        "sendMessage failed after %s attempts: %s",
                        max_attempts,
                        type(exc).__name__,
                        chat_id=chat_id,
                    )
                    return
                time.sleep(attempt)

    def send_with_buttons(self, chat_id: int, text: str, inline_buttons: list) -> None:
        keyboard = [
            [{"text": btn.label, "callback_data": btn.callback_data} for btn in row]
            for row in inline_buttons
        ]
        payload = {
            "chat_id": chat_id,
            "text": text,
            "reply_markup": {"inline_keyboard": keyboard},
        }
        max_attempts = 3
        button_count = sum(len(row) for row in inline_buttons)
        _outbound.info(
            "sendMessage buttons start len=%d rows=%d buttons=%d",
            len(text),
            len(inline_buttons),
            button_count,
            chat_id=chat_id,
        )
        for attempt in range(1, max_attempts + 1):
            try:
                response = httpx.post(
                    self._api_url,
                    json=payload,
                    timeout=httpx.Timeout(10.0, connect=5.0),
                )
                response.raise_for_status()
                _outbound.info(
                    "sent message with buttons len=%d attempt=%d status=%d",
                    len(text),
                    attempt,
                    response.status_code,
                    chat_id=chat_id,
                )
                return
            except httpx.HTTPError as exc:
                _outbound.warning(
                    "sendMessage buttons attempt failed attempt=%d/%d err=%s",
                    attempt,
                    max_attempts,
                    type(exc).__name__,
                    chat_id=chat_id,
                )
                if attempt == max_attempts:
                    _outbound.warning(
                        "sendMessage (buttons) failed after %s attempts: %s",
                        max_attempts,
                        type(exc).__name__,
                        chat_id=chat_id,
                    )
                    return
                time.sleep(attempt)

    def answer_callback_query(self, callback_query_id: str) -> None:
        payload = {"callback_query_id": callback_query_id}
        max_attempts = 3
        _outbound.info("answerCallbackQuery start")
        for attempt in range(1, max_attempts + 1):
            try:
                response = httpx.post(
                    self._callback_answer_url,
                    json=payload,
                    timeout=httpx.Timeout(10.0, connect=5.0),
                )
                response.raise_for_status()
                _outbound.info("answerCallbackQuery sent attempt=%d status=%d", attempt, response.status_code)
                return
            except httpx.HTTPError as exc:
                _outbound.warning(
                    "answerCallbackQuery attempt failed attempt=%d/%d err=%s",
                    attempt,
                    max_attempts,
                    type(exc).__name__,
                )
                if attempt == max_attempts:
                    _outbound.warning("answerCallbackQuery failed after %s attempts", max_attempts)
                    return
                time.sleep(attempt)

    def send_job_accepted(self, job: Job) -> None:
        _outbound.info(
            "notify job accepted",
            chat_id=job.request.chat_id,
            job_id=job.id,
            project=job.request.project,
        )

        class _Btn:
            def __init__(self, label: str, callback_data: str) -> None:
                self.label = label
                self.callback_data = callback_data

        lines = [
            "✅ 작업 접수 완료",
            "",
            f"- Job ID: {job.id}",
            f"- 프로젝트: {job.request.project}",
            f"- 모델: {job.request.model.value}",
        ]
        if job.request.mode is JobMode.PLAN:
            lines.append("- 모드: plan")
        elif job.request.mode is JobMode.ASK:
            lines.append("- 모드: ask")
        self.send_with_buttons(
            job.request.chat_id,
            "\n".join(lines),
            [[_Btn("작업 중단", f"/stop {job.id}")]],
        )

    def send_job_result(self, job: Job) -> None:
        _outbound.info(
            "notify job result status=%s changed_files=%d",
            job.status.value,
            len(job.changed_files),
            chat_id=job.request.chat_id,
            job_id=job.id,
            project=job.request.project,
        )
        mode_prefix = ""
        if job.request.mode is JobMode.PLAN:
            mode_prefix = "[plan] "
        elif job.request.mode is JobMode.ASK:
            mode_prefix = "[ask] "

        if job.status.value == "cancelled":
            text = (
                f"{mode_prefix}⛔ 작업 중단됨\n\n"
                f"- Job ID: {job.id}\n"
                f"- 프로젝트: {job.request.project}"
            )
            self.send_long_text(job.request.chat_id, text)
            return
        if job.status.value == "succeeded":
            if job.request.mode in (JobMode.PLAN, JobMode.ASK):
                label = "plan" if job.request.mode is JobMode.PLAN else "ask"
                text = (
                    f"[{label}] 응답 완료\n\n"
                    f"- Job ID: {job.id}\n"
                    f"- 프로젝트: {job.request.project}\n"
                    f"- 사용 모델: {job.runner_actual_model or job.request.model.value}\n"
                    f"- 토큰 사용량: {format_token_usage(job.runner_token_usage) or '확인 불가'}"
                )
                if job.runner_stdout_summary:
                    text += f"\n\nAI 응답:\n{job.runner_stdout_summary}"
            else:
                changed = ", ".join(job.changed_files) if job.changed_files else "변경 없음"
                branch_line = job.branch if job.branch else "(없음 — 변경 없어 브랜치 미생성)"
                commit_line = job.commit_hash or "-"
                if job.changed_files and not job.request.commit:
                    commit_line = "(no commit 옵션 — 커밋·push 생략)"
                elif job.changed_files and job.request.commit and not job.commit_hash:
                    commit_line = "(스테이징된 변경 없음 — push 생략)"
                text = (
                    f"✅ 작업 완료\n\n"
                    f"- Job ID: {job.id}\n"
                    f"- 프로젝트: {job.request.project}\n"
                    f"- 브랜치: {branch_line}\n"
                    f"- 커밋: {commit_line}\n"
                    f"- 변경 파일: {changed}\n"
                    f"- 사용 모델: {job.runner_actual_model or job.request.model.value}\n"
                    f"- 토큰 사용량: {format_token_usage(job.runner_token_usage) or '확인 불가'}"
                )
                if job.runner_stdout_summary:
                    text += f"\n\nAI 응답:\n{job.runner_stdout_summary}"
        else:
            details = []
            if job.error_stage:
                details.append(f"- 실패 단계: {job.error_stage}")
            if job.log_path:
                details.append(f"- 로그 경로: {job.log_path}")
            text = (
                f"{mode_prefix}❌ 작업 실패\n\n"
                f"- Job ID: {job.id}\n"
                f"- 프로젝트: {job.request.project}\n"
                f"- 오류: {job.error or 'unknown error'}"
            )
            if details:
                text += "\n" + "\n".join(details)
            failure_summary = job.runner_stderr_summary or job.runner_stdout_summary
            if failure_summary:
                text += f"\n\n실패 출력 요약:\n{failure_summary}"
        self.send_long_text(job.request.chat_id, text)

    def send_long_text(self, chat_id: int, text: str) -> None:
        """Telegram 단일 메시지 한도(4096자)를 넘으면 여러 메시지로 나눠 전송합니다."""
        chunks = self._chunk_text(text, self._TELEGRAM_TEXT_LIMIT)
        _outbound.info(
            "send_long_text chunks=%d total_len=%d",
            len(chunks),
            len(text),
            chat_id=chat_id,
        )
        for idx, chunk in enumerate(chunks, 1):
            _outbound.info(
                "send_long_text chunk=%d/%d len=%d",
                idx,
                len(chunks),
                len(chunk),
                chat_id=chat_id,
            )
            self.send_text(chat_id, chunk)

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
