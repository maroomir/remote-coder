from app.jobs.schemas import Job, JobRequest, JobStatus
from app.jobs.store import InMemoryJobStore
from app.models import ModelName
from app.telegram.commands import (
    CommandContext,
    CommandRegistry,
    HelpCommand,
    ModelCommand,
    ProjectsCommand,
    StartCommand,
    StatusCommand,
    TelegramMessage,
)
from app.telegram.model_preferences import InMemoryModelPreferenceStore


def _ctx():
    store = InMemoryJobStore()
    job = Job(
        id="job1",
        request=JobRequest(
            project="proj", model=ModelName.CLAUDE, instruction="x", chat_id=1, requested_by=1
        ),
        status=JobStatus.QUEUED,
    )
    store.create(job)
    return CommandContext(
        job_store=store,
        default_model=ModelName.CLAUDE,
        projects=["proj"],
        model_preferences=InMemoryModelPreferenceStore(default_model=ModelName.CLAUDE),
    )


def test_help_command_dispatch():
    registry = CommandRegistry([StartCommand(), HelpCommand(), ModelCommand(), StatusCommand(), ProjectsCommand()])
    text = registry.dispatch(TelegramMessage(chat_id=1, user_id=1, text="/help"), _ctx())
    assert text is not None and "/status <job_id>" in text


def test_status_command_dispatch():
    registry = CommandRegistry([StatusCommand()])
    text = registry.dispatch(TelegramMessage(chat_id=1, user_id=1, text="/status job1"), _ctx())
    assert text == "Job job1 상태: queued"


def test_model_command_updates_preference():
    registry = CommandRegistry([ModelCommand()])
    ctx = _ctx()
    text = registry.dispatch(TelegramMessage(chat_id=77, user_id=1, text="/model codex"), ctx)
    assert text == "기본 모델이 codex로 변경되었습니다."
    current = registry.dispatch(TelegramMessage(chat_id=77, user_id=1, text="/model"), ctx)
    assert current == "현재 기본 모델: codex"
