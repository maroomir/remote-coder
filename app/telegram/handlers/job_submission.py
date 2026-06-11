from __future__ import annotations

from collections.abc import Callable

from fastapi import BackgroundTasks

from app.ai.model_catalog import format_model_selection
from app.ai.usage import format_token_usage
from app.jobs.manager import JobManager
from app.jobs.schemas import Job, JobMode, JobRequest
from app.monitoring.events import EventLogger
from app.telegram.conversation import SQLiteConversationStore

_cmdlog = EventLogger("app.telegram.command", "telegram.command")
_JOB_RESULT_MEMORY_READ_ONLY_STDOUT_PREVIEW = 800


def format_job_result_memory_summary(final_job: Job) -> str:
    summary = f"status={final_job.status.value}"
    if final_job.error_stage:
        summary += f" stage={final_job.error_stage}"
    if final_job.error:
        summary += f" err={str(final_job.error)[:300]}"
    requested_model = format_model_selection(final_job.request.model, final_job.request.model_id)
    summary += f" model={final_job.runner_actual_model or requested_model}"
    token_usage = format_token_usage(final_job.runner_token_usage)
    if token_usage:
        summary += f" tokens={token_usage}"
    if final_job.request.mode in (JobMode.PLAN, JobMode.ASK) and final_job.runner_stdout_summary:
        preview = final_job.runner_stdout_summary[:_JOB_RESULT_MEMORY_READ_ONLY_STDOUT_PREVIEW]
        summary += f" stdout_preview={preview}"
    return summary


class JobSubmission:
    def __init__(
        self,
        *,
        job_manager: JobManager,
        conversation_store: SQLiteConversationStore | None,
        attach_session: Callable[[JobRequest], None],
        persist_session_token: Callable[[Job], None],
    ) -> None:
        self._job_manager = job_manager
        self._conversation_store = conversation_store
        self._attach_session = attach_session
        self._persist_session_token = persist_session_token

    def submit_fix(
        self,
        request: JobRequest,
        original_text: str,
        background_tasks: BackgroundTasks,
    ) -> None:
        if self._conversation_store is not None:
            self._conversation_store.append(
                project=request.project,
                chat_id=request.chat_id,
                role="user",
                text=original_text,
                message_id=request.message_id,
                reply_to_message_id=request.reply_to_message_id,
            )
            _cmdlog.info(
                "conversation fix user message recorded message_id=%s",
                request.message_id,
                chat_id=request.chat_id,
                user_id=request.requested_by,
                project=request.project,
            )

        self._attach_session(request)

        def run_and_record_fix() -> None:
            final_job = self._job_manager.execute_fix_job(request)
            self._persist_session_token(final_job)
            _cmdlog.info(
                "fix background run finished status=%s",
                final_job.status.value,
                chat_id=final_job.request.chat_id,
                user_id=final_job.request.requested_by,
                project=final_job.request.project,
                job_id=final_job.id,
            )
            if self._conversation_store is None:
                return
            self._conversation_store.append(
                project=final_job.request.project,
                chat_id=final_job.request.chat_id,
                role="job_accepted",
                text=f"Job accepted: {final_job.id}",
                job_id=final_job.id,
                message_id=final_job.accepted_message_id,
            )
            self._conversation_store.append(
                project=final_job.request.project,
                chat_id=final_job.request.chat_id,
                role="job_result",
                text=format_job_result_memory_summary(final_job),
                job_id=final_job.id,
                message_id=(
                    final_job.result_message_ids[0] if final_job.result_message_ids else None
                ),
            )
            if final_job.request.message_id is not None and final_job.branch is not None:
                self._conversation_store.bind_message_branch(
                    project=final_job.request.project,
                    chat_id=final_job.request.chat_id,
                    message_id=final_job.request.message_id,
                    branch=final_job.branch,
                    job_id=final_job.id,
                )

        background_tasks.add_task(run_and_record_fix)

    def submit_natural(
        self,
        request: JobRequest,
        original_text: str,
        background_tasks: BackgroundTasks,
    ) -> Job:
        if self._conversation_store is not None:
            self._conversation_store.append(
                project=request.project,
                chat_id=request.chat_id,
                role="user",
                text=original_text,
                message_id=request.message_id,
                reply_to_message_id=request.reply_to_message_id,
            )
            _cmdlog.info(
                "conversation user message recorded message_id=%s",
                request.message_id,
                chat_id=request.chat_id,
                user_id=request.requested_by,
                project=request.project,
            )

        self._attach_session(request)
        job = self._job_manager.submit(request)
        _cmdlog.info(
            "job accepted background scheduled",
            chat_id=request.chat_id,
            user_id=request.requested_by,
            project=request.project,
            job_id=job.id,
        )

        if self._conversation_store is not None and request.message_id is not None:
            self._conversation_store.bind_user_message_job(
                project=request.project,
                chat_id=request.chat_id,
                message_id=request.message_id,
                job_id=job.id,
            )

        if (
            self._conversation_store is not None
            and request.message_id is not None
            and request.branch is not None
        ):
            self._conversation_store.bind_message_branch(
                project=request.project,
                chat_id=request.chat_id,
                message_id=request.message_id,
                branch=request.branch,
                job_id=job.id,
            )

        if self._conversation_store is not None:
            self._conversation_store.append(
                project=request.project,
                chat_id=request.chat_id,
                role="job_accepted",
                text=f"Job accepted: {job.id}",
                job_id=job.id,
                message_id=getattr(job, "accepted_message_id", None),
            )
            _cmdlog.info(
                "conversation job_accepted recorded",
                chat_id=request.chat_id,
                user_id=request.requested_by,
                project=request.project,
                job_id=job.id,
            )

        if self._conversation_store is not None:

            def run_and_record(jid: str) -> None:
                _cmdlog.info("background job run start", job_id=jid)
                final_job = self._job_manager.run(jid)
                if final_job is None:
                    _cmdlog.warning("background job run returned none", job_id=jid)
                    return
                self._persist_session_token(final_job)
                self._conversation_store.append(
                    project=final_job.request.project,
                    chat_id=final_job.request.chat_id,
                    role="job_result",
                    text=format_job_result_memory_summary(final_job),
                    job_id=final_job.id,
                    message_id=(
                        final_job.result_message_ids[0]
                        if final_job.result_message_ids
                        else None
                    ),
                )
                _cmdlog.info(
                    "conversation job_result recorded status=%s",
                    final_job.status.value,
                    chat_id=final_job.request.chat_id,
                    user_id=final_job.request.requested_by,
                    project=final_job.request.project,
                    job_id=final_job.id,
                )
                if final_job.request.message_id is not None and final_job.branch is not None:
                    self._conversation_store.bind_message_branch(
                        project=final_job.request.project,
                        chat_id=final_job.request.chat_id,
                        message_id=final_job.request.message_id,
                        branch=final_job.branch,
                        job_id=final_job.id,
                    )
                    _cmdlog.info(
                        "conversation branch binding recorded branch=%s",
                        final_job.branch,
                        chat_id=final_job.request.chat_id,
                        user_id=final_job.request.requested_by,
                        project=final_job.request.project,
                        job_id=final_job.id,
                    )

            background_tasks.add_task(run_and_record, job.id)
        else:
            background_tasks.add_task(self._job_manager.run, job.id)
        return job
