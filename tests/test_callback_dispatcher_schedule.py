from unittest.mock import Mock

from fastapi import BackgroundTasks

from app.jobs.schedule_store import InMemoryScheduleStore
from app.jobs.schemas import JobMode
from app.models import ModelName
from app.projects.registry import ProjectRegistry
from app.security.auth import AllowlistAuthService
from app.telegram.commands import CommandContext, CommandRegistry, build_default_commands
from app.telegram.confirmations import InMemoryConfirmationStore
from app.telegram.handlers.callback_dispatcher import CallbackDispatcher
from app.telegram.handlers.request import (
    TelegramCallbackQuery,
    TelegramCallbackQueryFrom,
    TelegramCallbackQueryMessage,
    TelegramChat,
    TelegramUpdate,
)
from app.telegram.model_preferences import InMemoryModelPreferenceStore


def _dispatcher() -> CallbackDispatcher:
    return CallbackDispatcher(
        command_registry=CommandRegistry(build_default_commands()),
        submit_confirmed_natural_request=lambda *a, **k: None,
        submit_confirmed_fix_request=lambda *a, **k: None,
        handle_plan_execute=lambda *a, **k: {"status": "ok"},
        handle_plan_decision_answer=lambda *a, **k: {"status": "ok"},
        plan_execute_callback_prefix="__plan_exec__",
        plan_decision_callback_prefix="__plan_decision__",
    )


def _ctx(project_registry: ProjectRegistry, schedule_store) -> CommandContext:
    return CommandContext(
        job_store=Mock(),
        default_model=ModelName.CLAUDE,
        project_registry=project_registry,
        model_preferences=InMemoryModelPreferenceStore(default_model=ModelName.CLAUDE),
        project_name=project_registry.get_default_project_name(),
        git_service=Mock(),
        git_remote_name="origin",
        conversation_store=None,
        confirmation_store=InMemoryConfirmationStore(),
        advanced_settings_store=None,
        schedule_store=schedule_store,
    )


def _callback(data: str) -> tuple[TelegramUpdate, TelegramCallbackQuery]:
    cq = TelegramCallbackQuery(
        id="cb1",
        **{"from": TelegramCallbackQueryFrom(id=1)},
        message=TelegramCallbackQueryMessage(chat=TelegramChat(id=1), message_id=99),
        data=data,
    )
    return TelegramUpdate(update_id=1, callback_query=cq), cq


def _make_schedule(store, *, schedule_id, project, chat_id):
    from app.jobs.schedule import ScheduleRecord

    store.create(
        ScheduleRecord(
            id=schedule_id,
            project=project,
            chat_id=chat_id,
            mode=JobMode.RESEARCH,
            model=ModelName.CLAUDE,
            instruction="audit",
            interval_seconds=3600,
        )
    )


def test_schedule_delete_ask_sets_pending_confirmation(project_registry: ProjectRegistry):
    store = InMemoryScheduleStore()
    project = project_registry.get_default_project_name()
    _make_schedule(store, schedule_id="sch_abc123", project=project, chat_id=1)
    ctx = _ctx(project_registry, store)
    notifier = Mock()
    notifier.edit_message.return_value = True
    auth = AllowlistAuthService({1}, set())
    update, cq = _callback("__schedule_delete__:ask:sch_abc123")

    result = _dispatcher().handle(
        update, cq, notifier, auth, ctx, project, BackgroundTasks()
    )

    assert result["status"] == "ok"
    pending = ctx.confirmation_store.get(project, 1)
    assert pending is not None
    assert pending.command_name == "/schedule"
    assert pending.action == "sch_abc123"
    notifier.answer_callback_query.assert_called_once()


def test_schedule_delete_ask_rejects_other_chats_schedule(project_registry: ProjectRegistry):
    store = InMemoryScheduleStore()
    project = project_registry.get_default_project_name()
    _make_schedule(store, schedule_id="sch_other", project=project, chat_id=999)
    ctx = _ctx(project_registry, store)
    notifier = Mock()
    auth = AllowlistAuthService({1}, set())
    update, cq = _callback("__schedule_delete__:ask:sch_other")

    result = _dispatcher().handle(
        update, cq, notifier, auth, ctx, project, BackgroundTasks()
    )

    # Cross-chat id must not stage a pending delete.
    assert result["status"] == "ignored"
    assert ctx.confirmation_store.get(project, 1) is None
