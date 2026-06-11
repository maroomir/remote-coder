from __future__ import annotations

from app.jobs.schemas import Job, JobRequest
from app.telegram.conversation import SQLiteConversationStore


class SessionBinding:
    def __init__(self, conversation_store: SQLiteConversationStore | None) -> None:
        self._conversation_store = conversation_store

    def attach_session(self, request: JobRequest) -> None:
        if self._conversation_store is None or request.message_id is None:
            return
        session_id = self._conversation_store.resolve_or_create_session(
            request.project,
            request.chat_id,
            request.message_id,
            request.reply_to_message_id,
        )
        request.session_id = session_id
        request.resume_session_token = self._conversation_store.get_runner_resume_token(
            session_id, request.model.value
        )

    def refresh_resume_token(self, request: JobRequest) -> None:
        # Derived requests (PLAN phase B, plan-execute AGENT) carry session_id inherited from
        # the parent but have no Telegram message id; pick up the freshest runner token here.
        if self._conversation_store is None or request.session_id is None:
            return
        request.resume_session_token = self._conversation_store.get_runner_resume_token(
            request.session_id, request.model.value
        )

    def persist_session_token(self, final_job: Job) -> None:
        if (
            self._conversation_store is None
            or final_job.request.session_id is None
            or final_job.runner_session_id is None
        ):
            return
        self._conversation_store.set_runner_resume_token(
            final_job.request.session_id,
            final_job.request.model.value,
            final_job.runner_session_id,
        )
