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
    return CommandContext(job_store=store, default_model=ModelName.CLAUDE, projects=["proj"])


def test_help_command_dispatch():
    registry = CommandRegistry([StartCommand(), HelpCommand(), ModelCommand(), StatusCommand(), ProjectsCommand()])
    text = registry.dispatch(TelegramMessage(chat_id=1, user_id=1, text="/help"), _ctx())
    assert text is not None and "/status <job_id>" in text


def test_status_command_dispatch():
    registry = CommandRegistry([StatusCommand()])
    text = registry.dispatch(TelegramMessage(chat_id=1, user_id=1, text="/status job1"), _ctx())
    assert text == "Job job1 상태: queued"
