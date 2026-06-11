from __future__ import annotations

from collections.abc import Callable
from functools import partial
from threading import Lock

from fastapi import BackgroundTasks

from app.jobs.plan_decisions import (
    PlanDecisionAnswer,
    PlanDecisionQuestion,
    compose_execute_plan_instruction,
    compose_phase_b_instruction,
)
from app.jobs.schemas import Job, JobMode, JobRequest
from app.jobs.store import JobStore
from app.monitoring.events import EventLogger
from app.telegram.bot_instances import BotInstanceManager
from app.telegram.handlers.request import TelegramCallbackQuery
from app.telegram.notifier import Notifier
from app.telegram.plan_decisions_flow import (
    PendingPlanDecision,
    PlanDecisionStore,
    build_question_message,
    parse_decision_callback,
)

_cmdlog = EventLogger("app.telegram.command", "telegram.command")


class PlanFlow:
    def __init__(
        self,
        *,
        bot_instance_manager: BotInstanceManager,
        job_store: JobStore,
        plan_decision_store: PlanDecisionStore,
        executed_plan_jobs: set[str],
        executed_plan_jobs_lock: Lock,
        submit_confirmed_natural_request: Callable[[JobRequest, str, BackgroundTasks], Job],
        refresh_resume_token: Callable[[JobRequest], None],
    ) -> None:
        self._bot_instance_manager = bot_instance_manager
        self._job_store = job_store
        self._plan_decision_store = plan_decision_store
        self._executed_plan_jobs = executed_plan_jobs
        self._executed_plan_jobs_lock = executed_plan_jobs_lock
        self._submit_confirmed_natural_request = submit_confirmed_natural_request
        self._refresh_resume_token = refresh_resume_token

    def start_decisions(self, job: Job, questions: list[PlanDecisionQuestion]) -> bool:
        # Invoked from the JobManager background thread when a PLAN runner asked for decisions.
        instance = self._bot_instance_manager.get_by_name(job.request.project)
        if instance is None:
            return False
        pending = PendingPlanDecision(
            original_request=job.request,
            original_text=job.request.instruction,
            questions=questions,
        )
        self._plan_decision_store.set(job.request.project, job.request.chat_id, pending)
        text, rows = build_question_message(pending)
        instance.notifier.send_with_buttons(
            job.request.chat_id, text, rows, skip_body_i18n=True
        )
        _cmdlog.info(
            "plan decisions started questions=%d",
            len(questions),
            chat_id=job.request.chat_id,
            project=job.request.project,
            job_id=job.id,
        )
        return True

    def handle_decision_answer(
        self,
        cq: TelegramCallbackQuery,
        notifier: Notifier,
        scope_project: str | None,
        cq_chat_id: int,
        background_tasks: BackgroundTasks,
    ) -> dict[str, str]:
        parsed = parse_decision_callback(cq.data or "")
        pending = self._plan_decision_store.get(scope_project, cq_chat_id)
        if parsed is None or pending is None or pending.is_complete:
            notifier.answer_callback_query(cq.id)
            if pending is None:
                background_tasks.add_task(
                    notifier.send_text, cq_chat_id, "There is no pending decision."
                )
            return {"status": "ignored"}
        question_index, option_index = parsed
        question = pending.current_question
        if question_index != pending.current_index or not (
            0 <= option_index < len(question.options)
        ):
            # Stale or out-of-order tap (e.g. an already-answered question); ignore quietly.
            notifier.answer_callback_query(cq.id)
            return {"status": "ignored"}
        option = question.options[option_index]
        pending.answers.append(PlanDecisionAnswer(question=question, option=option))
        pending.current_index += 1
        notifier.answer_callback_query(cq.id, text=option.label)
        if cq.message is not None and cq.message.message_id is not None:
            background_tasks.add_task(
                partial(
                    notifier.edit_message,
                    cq_chat_id,
                    cq.message.message_id,
                    f"✅ {question.header}: {option.label}",
                    [],
                    skip_body_i18n=True,
                )
            )
        if pending.is_complete:
            self._plan_decision_store.pop(scope_project, cq_chat_id)
            phase_b_request = pending.original_request.model_copy(
                update={
                    "instruction": compose_phase_b_instruction(
                        pending.original_request.instruction, pending.answers
                    ),
                    "plan_decisions_resolved": True,
                    "job_id": None,
                    "message_id": None,
                    "reply_to_message_id": None,
                }
            )
            # Phase B continues the same logical conversation as phase A; reuse its session
            # and pick up the runner token phase A just persisted.
            self._refresh_resume_token(phase_b_request)
            _cmdlog.info(
                "plan decisions complete answers=%d",
                len(pending.answers),
                chat_id=cq_chat_id,
                project=scope_project,
            )
            job = self._submit_confirmed_natural_request(
                request=phase_b_request,
                original_text=pending.original_text,
                background_tasks=background_tasks,
            )
            return {"status": "accepted", "job_id": job.id}
        text, rows = build_question_message(pending)
        background_tasks.add_task(
            partial(notifier.send_with_buttons, cq_chat_id, text, rows, skip_body_i18n=True)
        )
        return {"status": "ok"}

    def handle_execute(
        self,
        cq: TelegramCallbackQuery,
        notifier: Notifier,
        scope_project: str | None,
        cq_chat_id: int,
        cq_user_id: int,
        background_tasks: BackgroundTasks,
    ) -> dict[str, str]:
        job_id = (cq.data or "").split(":", 1)[1]
        plan_job = self._job_store.get(job_id)
        if (
            plan_job is None
            or plan_job.request.project != scope_project
            or plan_job.request.chat_id != cq_chat_id
            or plan_job.status.value != "succeeded"
            or plan_job.request.mode is not JobMode.PLAN
        ):
            notifier.answer_callback_query(cq.id)
            background_tasks.add_task(
                notifier.send_text, cq_chat_id, "That plan can no longer be run."
            )
            return {"status": "ignored"}
        with self._executed_plan_jobs_lock:
            already_started = job_id in self._executed_plan_jobs
            if not already_started:
                self._executed_plan_jobs.add(job_id)
        if already_started:
            notifier.answer_callback_query(cq.id, text="Already started.")
            return {"status": "ignored"}
        agent_request = JobRequest(
            project=plan_job.request.project,
            model=plan_job.request.model,
            model_id=plan_job.request.model_id,
            instruction=compose_execute_plan_instruction(
                plan_job.request.instruction, plan_job.runner_stdout_summary or ""
            ),
            mode=JobMode.AGENT,
            parent_job_id=job_id,
            chat_id=cq_chat_id,
            requested_by=cq_user_id,
            session_id=plan_job.request.session_id,
        )
        # Inherit the plan's logical session so the implementation reuses the same runner
        # rollout instead of paying for a fresh session.
        self._refresh_resume_token(agent_request)
        notifier.answer_callback_query(cq.id, text="Running the plan…")
        _cmdlog.info(
            "plan execute accepted plan_job=%s",
            job_id,
            chat_id=cq_chat_id,
            project=scope_project,
        )
        job = self._submit_confirmed_natural_request(
            request=agent_request,
            original_text=f"Run plan {job_id}",
            background_tasks=background_tasks,
        )
        return {"status": "accepted", "job_id": job.id}
