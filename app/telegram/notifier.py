from __future__ import annotations

import logging
import time

import httpx

from app.jobs.schemas import Job


logger = logging.getLogger(__name__)


class TelegramNotifier:
    _TELEGRAM_TEXT_LIMIT = 4096

    def __init__(self, bot_token: str) -> None:
        self._api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    def send_text(self, chat_id: int, text: str) -> None:
        payload = {"chat_id": chat_id, "text": text}
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                response = httpx.post(
                    self._api_url,
                    json=payload,
                    timeout=httpx.Timeout(10.0, connect=5.0),
                )
                response.raise_for_status()
                return
            except httpx.HTTPError as exc:
                if attempt == max_attempts:
                    logger.warning(
                        "Telegram sendMessage failed after %s attempts: %s",
                        max_attempts,
                        type(exc).__name__,
                    )
                    return
                time.sleep(attempt)

    def send_job_accepted(self, job: Job) -> None:
        self.send_text(
            job.request.chat_id,
            f"작업 접수 완료\nJob ID: {job.id}\n프로젝트: {job.request.project}\n모델: {job.request.model.value}",
        )

    def send_job_result(self, job: Job) -> None:
        if job.status.value == "succeeded":
            changed = ", ".join(job.changed_files) if job.changed_files else "변경 없음"
            text = (
                f"작업 완료\n"
                f"Job ID: {job.id}\n"
                f"프로젝트: {job.request.project}\n"
                f"브랜치: {job.branch}\n"
                f"커밋: {job.commit_hash or '-'}\n"
                f"변경 파일: {changed}"
            )
            if job.runner_stdout_summary:
                text += f"\n\nAI 응답:\n{job.runner_stdout_summary}"
        else:
            details = []
            if job.error_stage:
                details.append(f"실패 단계: {job.error_stage}")
            if job.log_path:
                details.append(f"로그 경로: {job.log_path}")
            text = (
                f"작업 실패\n"
                f"Job ID: {job.id}\n"
                f"프로젝트: {job.request.project}\n"
                f"오류: {job.error or 'unknown error'}"
            )
            if details:
                text += "\n" + "\n".join(details)
            failure_summary = job.runner_stderr_summary or job.runner_stdout_summary
            if failure_summary:
                text += f"\n\n실패 출력 요약:\n{failure_summary}"
        self.send_text(job.request.chat_id, self._truncate_text(text))

    def _truncate_text(self, text: str) -> str:
        if len(text) <= self._TELEGRAM_TEXT_LIMIT:
            return text
        suffix = "\n...(truncated)"
        allowed = self._TELEGRAM_TEXT_LIMIT - len(suffix)
        return text[:allowed].rstrip() + suffix
