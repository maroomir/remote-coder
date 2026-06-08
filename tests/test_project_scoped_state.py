from unittest.mock import Mock

from app.jobs.schemas import Job, JobRequest, JobStatus
from app.jobs.store import InMemoryJobStore
from app.models import ModelName
from app.projects.registry import ProjectRecord, ProjectRegistry
from app.telegram.commands import (
    CommandContext,
    CommandRegistry,
    InlineButton,
    ModelCommand,
    StatusCommand,
    StopCommand,
    TelegramMessage,
)
from app.telegram.confirmations import InMemoryConfirmationStore, PendingConfirmation
from app.telegram.model_preferences import InMemoryModelPreferenceStore


def test_model_preferences_isolated_per_project_same_chat_id():
    pref = InMemoryModelPreferenceStore(default_model=ModelName.CLAUDE)
    pref.set("proj-a", 100, ModelName.CODEX)
    pref.set("proj-b", 100, ModelName.GEMINI)
    assert pref.get("proj-a", 100) == ModelName.CODEX
    assert pref.get("proj-b", 100) == ModelName.GEMINI


def test_confirmations_isolated_per_project_same_chat_id():
    conf = InMemoryConfirmationStore()
    conf.set(
        "proj-a",
        50,
        PendingConfirmation(command_name="/clear", action="memory"),
    )
    assert conf.get("proj-a", 50) is not None
    assert conf.get("proj-b", 50) is None


def test_status_lists_only_jobs_for_bot_project(project_registry: ProjectRegistry):
    root_a = project_registry.config_path.parent / "psc_a_repo"
    root_a.mkdir()
    project_registry.add_project(
        ProjectRecord(
            name="proj-a",
            root_path=root_a,
            default_model=ModelName.CLAUDE,
            enabled=True,
            bot_token="123:psc_a",
            allowed_chat_ids=[1],
        )
    )
    root_b = project_registry.config_path.parent / "psc_b_repo"
    root_b.mkdir()
    project_registry.add_project(
        ProjectRecord(
            name="proj-b",
            root_path=root_b,
            default_model=ModelName.CLAUDE,
            enabled=True,
            bot_token="123:psc_b",
            allowed_chat_ids=[1],
        )
    )

    store = InMemoryJobStore()
    store.create(
        Job(
            id="job-a",
            request=JobRequest(
                project="proj-a",
                model=ModelName.CLAUDE,
                instruction="x",
                chat_id=999,
                requested_by=1,
            ),
            status=JobStatus.RUNNING,
        )
    )
    store.create(
        Job(
            id="job-b",
            request=JobRequest(
                project="proj-b",
                model=ModelName.CLAUDE,
                instruction="x",
                chat_id=999,
                requested_by=1,
            ),
            status=JobStatus.QUEUED,
        )
    )

    ctx = CommandContext(
        job_store=store,
        default_model=ModelName.CLAUDE,
        project_registry=project_registry,
        model_preferences=InMemoryModelPreferenceStore(default_model=ModelName.CLAUDE),
        project_name="proj-a",
        git_service=Mock(),
        git_remote_name="origin",
        confirmation_store=InMemoryConfirmationStore(),
    )

    registry = CommandRegistry([StatusCommand()])
    rich = registry.dispatch_rich(
        TelegramMessage(chat_id=999, user_id=1, text="/status"),
        ctx,
    )
    assert rich is not None
    assert rich.inline_buttons == [[InlineButton("job-a (running)", "/status job-a")]]

    hidden = registry.dispatch(
        TelegramMessage(chat_id=999, user_id=1, text="/status job-b"),
        ctx,
    )
    assert hidden == "Job ID not found."


def test_stop_does_not_cancel_job_from_other_project(project_registry: ProjectRegistry):
    store = InMemoryJobStore()
    store.create(
        Job(
            id="job-b",
            request=JobRequest(
                project="other-proj",
                model=ModelName.CLAUDE,
                instruction="x",
                chat_id=1,
                requested_by=1,
            ),
            status=JobStatus.QUEUED,
        )
    )
    job_manager = Mock()
    ctx = CommandContext(
        job_store=store,
        default_model=ModelName.CLAUDE,
        project_registry=project_registry,
        model_preferences=InMemoryModelPreferenceStore(default_model=ModelName.CLAUDE),
        project_name="remote-coder",
        git_service=Mock(),
        git_remote_name="origin",
        confirmation_store=InMemoryConfirmationStore(),
        job_manager=job_manager,
    )

    registry = CommandRegistry([StopCommand()])
    text = registry.dispatch(
        TelegramMessage(chat_id=1, user_id=1, text="/stop job-b"),
        ctx,
    )
    assert text == "Job not found: job-b"
    job_manager.cancel.assert_not_called()


def test_model_command_does_not_leak_across_projects(project_registry: ProjectRegistry):
    registry = CommandRegistry([ModelCommand()])
    pref = InMemoryModelPreferenceStore(default_model=ModelName.CLAUDE)
    ctx = CommandContext(
        job_store=InMemoryJobStore(),
        default_model=ModelName.CLAUDE,
        project_registry=project_registry,
        model_preferences=pref,
        project_name="remote-coder",
        git_service=Mock(),
        git_remote_name="origin",
        confirmation_store=InMemoryConfirmationStore(),
    )
    registry.dispatch(TelegramMessage(chat_id=42, user_id=1, text="/model codex"), ctx)
    assert pref.get("remote-coder", 42) == ModelName.CODEX
    assert pref.get_explicit("other-scoped", 42) is None
