from unittest.mock import Mock

from app.jobs.schedule_store import InMemoryScheduleStore
from app.jobs.schemas import JobMode
from app.models import ModelName
from app.projects.registry import ProjectRegistry
from app.telegram.commands import CommandContext, CommandRegistry, InlineButton, TelegramMessage
from app.telegram.commands.schedule import ScheduleCommand
from app.telegram.confirmations import InMemoryConfirmationStore
from app.telegram.model_preferences import InMemoryModelPreferenceStore


def _ctx(project_registry: ProjectRegistry, schedule_store=None) -> CommandContext:
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
        schedule_store=schedule_store or InMemoryScheduleStore(),
    )


def test_schedule_registers_read_only_job(project_registry: ProjectRegistry):
    store = InMemoryScheduleStore()
    ctx = _ctx(project_registry, store)

    text = ScheduleCommand().execute(
        TelegramMessage(chat_id=1, user_id=1, text="/schedule 6h research audit dependencies"),
        ctx,
    )

    assert "Scheduled" in text
    schedules = store.list_for_project_chat(project_registry.get_default_project_name(), 1)
    assert len(schedules) == 1
    assert schedules[0].mode is JobMode.RESEARCH
    assert schedules[0].interval_seconds == 6 * 3600
    assert schedules[0].instruction == "audit dependencies"


def test_schedule_rejects_write_mode(project_registry: ProjectRegistry):
    ctx = _ctx(project_registry)
    text = ScheduleCommand().execute(
        TelegramMessage(chat_id=1, user_id=1, text="/schedule 6h agent do the thing"), ctx
    )
    assert "read-only" in text


def test_schedule_rejects_bad_interval(project_registry: ProjectRegistry):
    ctx = _ctx(project_registry)
    text = ScheduleCommand().execute(
        TelegramMessage(chat_id=1, user_id=1, text="/schedule 5s ask quick"), ctx
    )
    assert "Interval must be" in text


def test_schedule_rejects_below_minimum_interval(project_registry: ProjectRegistry):
    ctx = _ctx(project_registry)
    # 30s is below the 60s floor and uses a valid unit form only via seconds, which is unsupported.
    text = ScheduleCommand().execute(
        TelegramMessage(chat_id=1, user_id=1, text="/schedule 0h ask quick"), ctx
    )
    assert "Interval must be" in text


def test_schedule_usage_when_incomplete(project_registry: ProjectRegistry):
    ctx = _ctx(project_registry)
    text = ScheduleCommand().execute(
        TelegramMessage(chat_id=1, user_id=1, text="/schedule 6h research"), ctx
    )
    assert "Usage" in text


def test_schedule_list_empty(project_registry: ProjectRegistry):
    ctx = _ctx(project_registry)
    text = ScheduleCommand().execute(TelegramMessage(chat_id=1, user_id=1, text="/schedule"), ctx)
    assert "No schedules yet" in text


def test_schedule_list_shows_buttons(project_registry: ProjectRegistry):
    store = InMemoryScheduleStore()
    ctx = _ctx(project_registry, store)
    cmd = ScheduleCommand()
    cmd.execute(
        TelegramMessage(chat_id=1, user_id=1, text="/schedule 1d ask weekly status"), ctx
    )

    msg = TelegramMessage(chat_id=1, user_id=1, text="/schedule")
    text = cmd.execute(msg, ctx)
    buttons = cmd.get_inline_buttons(msg, ctx)

    assert "Scheduled jobs" in text
    assert buttons is not None
    flat = [b for row in buttons for b in row]
    assert any(b.callback_data.startswith("__schedule_delete__:ask:") for b in flat)


def test_schedule_confirm_deletes(project_registry: ProjectRegistry):
    store = InMemoryScheduleStore()
    ctx = _ctx(project_registry, store)
    registry = CommandRegistry([ScheduleCommand()])
    ScheduleCommand().execute(
        TelegramMessage(chat_id=1, user_id=1, text="/schedule 6h research audit deps"), ctx
    )
    sched_id = store.list_for_project_chat(project_registry.get_default_project_name(), 1)[0].id

    # Simulate the pending set by the delete-ask callback, then confirm Yes.
    from app.telegram.confirmations import PendingConfirmation

    ctx.confirmation_store.set(
        project_registry.get_default_project_name(),
        1,
        PendingConfirmation(command_name="/schedule", action=sched_id),
    )
    text = registry.dispatch(
        TelegramMessage(chat_id=1, user_id=1, text="__schedule_delete__:yes"), ctx
    )

    assert "Schedule removed" in (text or "")
    assert store.get(sched_id) is None


def test_schedule_confirm_rejects_other_chats_schedule(project_registry: ProjectRegistry):
    # A schedule owned by chat 999 must not be deletable from chat 1, even with its id.
    store = InMemoryScheduleStore()
    ctx = _ctx(project_registry, store)
    from app.jobs.schedule import ScheduleRecord

    other = ScheduleRecord(
        id="sch_other",
        project=project_registry.get_default_project_name(),
        chat_id=999,
        mode=JobMode.RESEARCH,
        model=ModelName.CLAUDE,
        instruction="not yours",
        interval_seconds=3600,
    )
    store.create(other)
    registry = CommandRegistry([ScheduleCommand()])

    from app.telegram.confirmations import PendingConfirmation

    ctx.confirmation_store.set(
        project_registry.get_default_project_name(),
        1,
        PendingConfirmation(command_name="/schedule", action="sch_other"),
    )
    text = registry.dispatch(
        TelegramMessage(chat_id=1, user_id=1, text="__schedule_delete__:yes"), ctx
    )

    assert "no longer exists" in (text or "")
    assert store.get("sch_other") is not None


def test_schedule_confirm_no_keeps(project_registry: ProjectRegistry):
    store = InMemoryScheduleStore()
    ctx = _ctx(project_registry, store)
    registry = CommandRegistry([ScheduleCommand()])
    ScheduleCommand().execute(
        TelegramMessage(chat_id=1, user_id=1, text="/schedule 6h research audit deps"), ctx
    )
    sched_id = store.list_for_project_chat(project_registry.get_default_project_name(), 1)[0].id

    from app.telegram.confirmations import PendingConfirmation

    ctx.confirmation_store.set(
        project_registry.get_default_project_name(),
        1,
        PendingConfirmation(command_name="/schedule", action=sched_id),
    )
    text = registry.dispatch(
        TelegramMessage(chat_id=1, user_id=1, text="__schedule_delete__:no"), ctx
    )

    assert "cancelled" in (text or "")
    assert store.get(sched_id) is not None
