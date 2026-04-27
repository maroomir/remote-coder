from __future__ import annotations

import httpx

from app.jobs.schemas import Job


class TelegramNotifier:
    def __init__(self, bot_token: str) -> None:
        self._api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    def send_text(self, chat_id: int, text: str) -> None:
        payload = {"chat_id": chat_id, "text": text}
        response = httpx.post(self._api_url, json=payload, timeout=10.0)
        response.raise_for_status()

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
        else:
            text = (
                f"작업 실패\n"
                f"Job ID: {job.id}\n"
                f"프로젝트: {job.request.project}\n"
                f"오류: {job.error or 'unknown error'}"
            )
        self.send_text(job.request.chat_id, text)
