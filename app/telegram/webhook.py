from __future__ import annotations

from threading import Lock

from fastapi import APIRouter, BackgroundTasks, Header

from app.jobs.manager import JobManager
from app.jobs.plan_decisions import (
    PLAN_EXECUTE_CALLBACK_PREFIX,
    PlanDecisionQuestion,
)
from app.jobs.schemas import Job, JobRequest
from app.jobs.store import JobStore
from app.security.auth import AllowlistAuthService
from app.telegram.commands import (
    CommandContext,
    CommandRegistry,
)
from app.telegram.bot_instances import BotInstanceManager
from app.telegram.confirmations import PendingConfirmation
from app.telegram.conversation import SQLiteConversationStore
from app.telegram.handlers.callback_dispatcher import CallbackDispatcher
from app.telegram.handlers.command_flow import CommandFlow
from app.telegram.handlers.fix_flow import FixFlow
from app.telegram.handlers.job_submission import (
    JobSubmission,
    format_job_result_memory_summary,
)
from app.telegram.handlers.natural_flow import NaturalFlow
from app.telegram.handlers.plan_flow import PlanFlow
from app.telegram.handlers.recent_updates import RecentUpdateTracker as _RecentUpdateTracker
from app.telegram.handlers.request import (
    TelegramCallbackQuery,
    TelegramCallbackQueryFrom,
    TelegramCallbackQueryMessage,
    TelegramChat,
    TelegramIncomingMessage,
    TelegramReplyMessage,
    TelegramUpdate,
    TelegramUser,
    WebhookRequest as _Req,
)
from app.telegram.handlers.session_binding import SessionBinding
from app.telegram.handlers.update_handler import WebhookUpdateHandler
from app.telegram.notifier import Notifier
from app.telegram.parser import CommandParser
from app.telegram.plan_decisions_flow import (
    PLAN_DECISION_CALLBACK_PREFIX,
    PlanDecisionStore,
)


def create_webhook_router(
    bot_instance_manager: BotInstanceManager,
    parser: CommandParser,
    command_registry: CommandRegistry,
    job_manager: JobManager,
    job_store: JobStore,
    conversation_store: SQLiteConversationStore | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/telegram", tags=["telegram"])
    recent_updates = _RecentUpdateTracker()
    plan_decision_store = PlanDecisionStore()
    executed_plan_jobs: set[str] = set()
    executed_plan_jobs_lock = Lock()

    def _fix_flow() -> FixFlow:
        return FixFlow(
            parser=parser,
            job_manager=job_manager,
            conversation_store=conversation_store,
        )

    def _natural_flow() -> NaturalFlow:
        return NaturalFlow(parser=parser)

    def _session_binding() -> SessionBinding:
        return SessionBinding(conversation_store)

    def _job_submission() -> JobSubmission:
        return JobSubmission(
            job_manager=job_manager,
            conversation_store=conversation_store,
            attach_session=_attach_session,
            persist_session_token=_persist_session_token,
        )

    def _plan_flow() -> PlanFlow:
        return PlanFlow(
            bot_instance_manager=bot_instance_manager,
            job_store=job_store,
            plan_decision_store=plan_decision_store,
            executed_plan_jobs=executed_plan_jobs,
            executed_plan_jobs_lock=executed_plan_jobs_lock,
            submit_confirmed_natural_request=_submit_confirmed_natural_request,
            refresh_resume_token=_refresh_resume_token,
        )

    def _handle_callback_query(
        update: TelegramUpdate,
        cq: TelegramCallbackQuery,
        notifier: Notifier,
        auth_service: AllowlistAuthService,
        command_context: CommandContext,
        scope_project: str | None,
        background_tasks: BackgroundTasks,
    ) -> dict[str, str]:
        return CallbackDispatcher(
            command_registry=command_registry,
            submit_confirmed_natural_request=_submit_confirmed_natural_request,
            submit_confirmed_fix_request=_submit_confirmed_fix_request,
            handle_plan_execute=_handle_plan_execute,
            handle_plan_decision_answer=_handle_plan_decision_answer,
            plan_execute_callback_prefix=PLAN_EXECUTE_CALLBACK_PREFIX,
            plan_decision_callback_prefix=PLAN_DECISION_CALLBACK_PREFIX,
        ).handle(
            update,
            cq,
            notifier,
            auth_service,
            command_context,
            scope_project,
            background_tasks,
        )

    def _handle_fix_intent(req: _Req) -> dict[str, str] | None:
        return _fix_flow().handle_intent(req)

    def _attach_session(request: JobRequest) -> None:
        _session_binding().attach_session(request)

    def _refresh_resume_token(request: JobRequest) -> None:
        _session_binding().refresh_resume_token(request)

    def _persist_session_token(final_job: Job) -> None:
        _session_binding().persist_session_token(final_job)

    def _submit_confirmed_fix_request(
        request: JobRequest,
        original_text: str,
        background_tasks: BackgroundTasks,
    ) -> None:
        _job_submission().submit_fix(request, original_text, background_tasks)

    def _handle_pending(req: _Req, pending: PendingConfirmation | None) -> dict[str, str] | None:
        if pending is None:
            return None

        natural_pending_result = _natural_flow().handle_pending(req, pending)
        if natural_pending_result is not None:
            return natural_pending_result

        fix_pending_result = _fix_flow().handle_pending(req, pending)
        if fix_pending_result is not None:
            return fix_pending_result

        return None

    def _handle_command(req: _Req) -> dict[str, str] | None:
        return CommandFlow(command_registry=command_registry).handle_command(req)

    def _handle_natural(req: _Req) -> dict[str, str]:
        return _natural_flow().handle_natural(req)

    def _start_plan_decisions(job: Job, questions: list[PlanDecisionQuestion]) -> bool:
        return _plan_flow().start_decisions(job, questions)

    def _handle_plan_decision_answer(
        cq: TelegramCallbackQuery,
        notifier: Notifier,
        scope_project: str | None,
        cq_chat_id: int,
        background_tasks: BackgroundTasks,
    ) -> dict[str, str]:
        return _plan_flow().handle_decision_answer(
            cq, notifier, scope_project, cq_chat_id, background_tasks
        )

    def _handle_plan_execute(
        cq: TelegramCallbackQuery,
        notifier: Notifier,
        scope_project: str | None,
        cq_chat_id: int,
        cq_user_id: int,
        background_tasks: BackgroundTasks,
    ) -> dict[str, str]:
        return _plan_flow().handle_execute(
            cq, notifier, scope_project, cq_chat_id, cq_user_id, background_tasks
        )

    @router.post("/webhook/{token_hash}")
    def telegram_webhook(
        token_hash: str,
        update: TelegramUpdate,
        background_tasks: BackgroundTasks,
        x_telegram_bot_api_secret_token: str | None = Header(default=None),
    ) -> dict[str, str]:
        return WebhookUpdateHandler(
            bot_instance_manager=bot_instance_manager,
            recent_updates=recent_updates,
            plan_decision_store=plan_decision_store,
            handle_callback_query=_handle_callback_query,
            handle_pending=_handle_pending,
            handle_fix_intent=_handle_fix_intent,
            handle_command=_handle_command,
            handle_natural=_handle_natural,
            natural_flow_factory=_natural_flow,
            fix_flow_factory=_fix_flow,
        ).handle(
            token_hash,
            update,
            background_tasks,
            x_telegram_bot_api_secret_token,
        )

    def _submit_confirmed_natural_request(
        request: JobRequest,
        original_text: str,
        background_tasks: BackgroundTasks,
    ) -> Job:
        return _job_submission().submit_natural(request, original_text, background_tasks)

    job_manager.plan_decision_router = _start_plan_decisions
    return router
