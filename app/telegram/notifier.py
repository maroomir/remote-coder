from __future__ import annotations

import time

import httpx

from app.jobs.schemas import Job
from app.monitoring.events import EventLogger

_outbound = EventLogger("app.telegram.outbound", "telegram.outbound")


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
                _outbound.info(
                    "sent text len=%d attempt=%d",
                    len(text),
                    attempt,
                    chat_id=chat_id,
                )
                return
            except httpx.HTTPError as exc:
                if attempt == max_attempts:
                    _outbound.warning(
                        "sendMessage failed after %s attempts: %s",
                        max_attempts,
                        type(exc).__name__,
                        chat_id=chat_id,
                    )
                    return
                time.sleep(attempt)

    def send_job_accepted(self, job: Job) -> None:
        _outbound.info(
            "notify job accepted",
            chat_id=job.request.chat_id,
            job_id=job.id,
            project=job.request.project,
        )
        self.send_text(
            job.request.chat_id,
            f"작업 접수 완료\nJob ID: {job.id}\n프로젝트: {job.request.project}\n모델: {job.request.model.value}",
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
        if job.status.value == "succeeded":
            changed = ", ".join(job.changed_files) if job.changed_files else "변경 없음"
            branch_line = job.branch if job.branch else "(없음 — 변경 없어 브랜치 미생성)"
            commit_line = job.commit_hash or "-"
            if job.changed_files and not job.request.commit:
                commit_line = "(no commit 옵션 — 커밋·push 생략)"
            elif job.changed_files and job.request.commit and not job.commit_hash:
                commit_line = "(스테이징된 변경 없음 — push 생략)"
            text = (
                f"작업 완료\n"
                f"Job ID: {job.id}\n"
                f"프로젝트: {job.request.project}\n"
                f"브랜치: {branch_line}\n"
                f"커밋: {commit_line}\n"
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
        self.send_long_text(job.request.chat_id, text)

    def send_long_text(self, chat_id: int, text: str) -> None:
        """Telegram 단일 메시지 한도(4096자)를 넘으면 여러 메시지로 나눠 전송합니다."""
        for chunk in self._chunk_text(text, self._TELEGRAM_TEXT_LIMIT):
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
