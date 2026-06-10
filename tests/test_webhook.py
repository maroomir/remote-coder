import logging
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.admin.advanced_settings import AdvancedSettings
from app.jobs.schemas import Job, JobMode, JobRequest, JobStatus
from app.jobs.store import InMemoryJobStore
from app.models import ModelName
from app.projects.registry import ProjectRecord, ProjectRegistry, compute_token_hash_prefix
from app.security.auth import AllowlistAuthService
from app.telegram.bot_instances import BotInstance, BotInstanceManager
from app.telegram.commands import (
    BranchCommand,
    ClearCommand,
    CommandContext,
    CommandRegistry,
    HelpCommand,
    InitCommand,
    ModelCommand,
    RebaseCommand,
    StartCommand,
    StatusCommand,
    TelegramCommand,
)
from app.telegram.confirmations import InMemoryConfirmationStore
from app.telegram.conversation import SQLiteConversationStore
from app.telegram.model_preferences import InMemoryModelPreferenceStore
from app.telegram.parser import CommandParser
from app.telegram.webhook import (
    TelegramUpdate,
    _RecentUpdateTracker,
    create_webhook_router,
    format_job_result_memory_summary,
)


class DummyJob:
    id = "job_1"


class DummyJobManager:
    def submit(self, request):
        _ = request
        return DummyJob()

    def run(self, job_id: str):
        _ = job_id
        return None


class CaptureJobManager:
    def __init__(self) -> None:
        self.last_request = None

    def submit(self, request):
        self.last_request = request
        return DummyJob()

    def run(self, job_id: str):
        _ = job_id
        return None


class RecordedMessageJobManager:
    def __init__(self) -> None:
        self.job: Job | None = None

    def submit(self, request):
        self.job = Job(id=request.job_id or "job_recorded", request=request, accepted_message_id=200)
        return self.job

    def run(self, job_id: str):
        assert self.job is not None
        assert job_id == self.job.id
        self.job.status = JobStatus.SUCCEEDED
        self.job.runner_stdout_summary = "done"
        self.job.result_message_ids = [201]
        return self.job


def test_format_job_result_memory_summary_includes_usage():
    job = Job(
        id="job-usage",
        request=JobRequest(
            project="remote-coder",
            model=ModelName.CODEX,
            instruction="x",
            chat_id=1,
            requested_by=1,
        ),
        status=JobStatus.SUCCEEDED,
        runner_actual_model="ChatGPT 5.5",
        runner_token_usage={"input": 1200, "output": 300},
    )

    summary = format_job_result_memory_summary(job)

    assert "status=succeeded" in summary
    assert "model=ChatGPT 5.5" in summary
    assert "tokens=1,500" in summary


def test_format_job_result_memory_summary_plan_includes_stdout_preview():
    long_out = "X" * 900
    job = Job(
        id="job-plan",
        request=JobRequest(
            project="remote-coder",
            model=ModelName.CLAUDE,
            instruction="plan me",
            chat_id=1,
            requested_by=1,
            mode=JobMode.PLAN,
        ),
        status=JobStatus.SUCCEEDED,
        runner_stdout_summary=long_out,
    )
    summary = format_job_result_memory_summary(job)
    assert "stdout_preview=" in summary
    _, preview = summary.split("stdout_preview=", 1)
    assert preview == "X" * 800


def test_format_job_result_memory_summary_agent_no_stdout_preview_key():
    job = Job(
        id="job-agent",
        request=JobRequest(
            project="remote-coder",
            model=ModelName.CLAUDE,
            instruction="go",
            chat_id=1,
            requested_by=1,
            mode=JobMode.AGENT,
        ),
        status=JobStatus.SUCCEEDED,
        runner_stdout_summary="full agent output",
    )
    summary = format_job_result_memory_summary(job)
    assert "stdout_preview=" not in summary


class DummyNotifier:
    def __init__(self):
        self.sent: list[tuple[int, str]] = []
        self.sent_with_buttons: list[tuple[int, str, object]] = []
        self.answered_callbacks: list[str] = []

    def send_text(self, chat_id: int, text: str, **kwargs) -> None:
        self.sent.append((chat_id, text))

    def send_with_buttons(self, chat_id: int, text: str, inline_buttons, **kwargs) -> None:
        self.sent_with_buttons.append((chat_id, text, inline_buttons))

    def answer_callback_query(self, callback_query_id: str) -> None:
        self.answered_callbacks.append(callback_query_id)


def _webhook_url(project_registry: ProjectRegistry) -> str:
    record = project_registry.get("remote-coder")
    assert record is not None
    route_key = compute_token_hash_prefix(record.bot_token.get_secret_value())
    return f"/telegram/webhook/{route_key}"


def _bot_manager_for_project(
    project_registry: ProjectRegistry,
    *,
    auth_service: AllowlistAuthService,
    notifier: DummyNotifier,
    command_context: CommandContext,
    webhook_secret: str | None = None,
    project_name: str = "remote-coder",
) -> BotInstanceManager:
    record = project_registry.get(project_name)
    assert record is not None

    def factory(r: ProjectRecord) -> BotInstance:
        return BotInstance(
            project_name=r.name,
            token_hash=compute_token_hash_prefix(r.bot_token.get_secret_value()),
            notifier=notifier,
            auth_service=auth_service,
            command_context=command_context,
            webhook_secret=webhook_secret,
        )

    mgr = BotInstanceManager(factory)
    mgr.register(record)
    return mgr


def _commands_with_clear() -> CommandRegistry:
    return CommandRegistry(
        [
            StartCommand(),
            HelpCommand(),
            ModelCommand(),
            StatusCommand(),
            InitCommand(),
            BranchCommand(),
            RebaseCommand(),
            ClearCommand(),
        ]
    )


def test_webhook_accepts_natural_message(project_registry):
    app = FastAPI()
    store = InMemoryJobStore()
    notifier = DummyNotifier()
    git_service = Mock()
    git_service.get_current_branch.return_value = "main"
    command_context = CommandContext(
        job_store=store,
        default_model=ModelName.CLAUDE,
        project_registry=project_registry,
        model_preferences=InMemoryModelPreferenceStore(default_model=ModelName.CLAUDE),
        project_name=None,
        git_service=git_service,
        git_remote_name="origin",
        conversation_store=None,
        confirmation_store=InMemoryConfirmationStore(),
    )
    mgr = _bot_manager_for_project(
        project_registry,
        auth_service=AllowlistAuthService({123}),
        notifier=notifier,
        command_context=command_context,
    )
    app.include_router(
        create_webhook_router(
            bot_instance_manager=mgr,
            parser=CommandParser(
                project_registry=project_registry,
                default_model=ModelName.CLAUDE,
            ),
            command_registry=_commands_with_clear(),
            job_manager=DummyJobManager(),
            job_store=store,
            conversation_store=None,
        )
    )
    client = TestClient(app)
    wh = _webhook_url(project_registry)
    payload = {
        "update_id": 1,
        "message": {"message_id": 1, "text": "fix tests", "chat": {"id": 123}, "from": {"id": 999}},
    }
    response = client.post(wh, json=payload)
    confirm_response = client.post(
        wh,
        json={
            "update_id": 2,
            "message": {"message_id": 2, "text": "Y", "chat": {"id": 123}, "from": {"id": 999}},
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert notifier.sent[0][1].startswith("Confirm the work to run.")
    assert "- Project: remote-coder" in notifier.sent[0][1]
    assert "- Work branch: main" in notifier.sent[0][1]
    assert "- Model: claude" in notifier.sent[0][1]
    assert confirm_response.status_code == 200
    assert confirm_response.json()["status"] == "accepted"


def test_webhook_plan_mode_requires_confirmation_then_accepts_y(project_registry):
    app = FastAPI()
    store = InMemoryJobStore()
    notifier = DummyNotifier()
    git_service = Mock()
    git_service.get_current_branch.return_value = "main"
    job_manager = CaptureJobManager()
    command_context = CommandContext(
        job_store=store,
        default_model=ModelName.CLAUDE,
        project_registry=project_registry,
        model_preferences=InMemoryModelPreferenceStore(default_model=ModelName.CLAUDE),
        project_name=None,
        git_service=git_service,
        git_remote_name="origin",
        conversation_store=None,
        confirmation_store=InMemoryConfirmationStore(),
    )
    mgr = _bot_manager_for_project(
        project_registry,
        auth_service=AllowlistAuthService({123}),
        notifier=notifier,
        command_context=command_context,
    )
    app.include_router(
        create_webhook_router(
            bot_instance_manager=mgr,
            parser=CommandParser(
                project_registry=project_registry,
                default_model=ModelName.CLAUDE,
            ),
            command_registry=_commands_with_clear(),
            job_manager=job_manager,
            job_store=store,
            conversation_store=None,
        )
    )
    client = TestClient(app)
    wh = _webhook_url(project_registry)
    response = client.post(
        wh,
        json={
            "update_id": 10,
            "message": {
                "message_id": 10,
                "text": "plan: outline the refactor",
                "chat": {"id": 123},
                "from": {"id": 999},
            },
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json().get("job_id") is None
    pending = command_context.confirmation_store.get("remote-coder", 123)
    assert pending is not None
    assert pending.job_request is not None
    assert pending.job_request.mode == JobMode.PLAN
    assert "outline the refactor" in pending.job_request.instruction
    assert "- Mode: plan" in notifier.sent[0][1]
    git_service.get_current_branch.assert_called_once()

    confirm_response = client.post(
        wh,
        json={
            "update_id": 11,
            "message": {"message_id": 11, "text": "y", "chat": {"id": 123}, "from": {"id": 999}},
        },
    )
    assert confirm_response.status_code == 200
    assert confirm_response.json()["status"] == "accepted"
    assert confirm_response.json()["job_id"] == "job_1"
    assert command_context.confirmation_store.get("remote-coder", 123) is None
    assert job_manager.last_request is not None
    assert job_manager.last_request.mode == JobMode.PLAN


def test_webhook_binds_confirmed_plan_user_message_to_job_id(project_registry, tmp_path):
    app = FastAPI()
    store = InMemoryJobStore()
    conversation_store = SQLiteConversationStore(tmp_path / "conv.sqlite3")
    notifier = DummyNotifier()
    git_service = Mock()
    git_service.get_current_branch.return_value = "main"
    job_manager = CaptureJobManager()
    command_context = CommandContext(
        job_store=store,
        default_model=ModelName.CLAUDE,
        project_registry=project_registry,
        model_preferences=InMemoryModelPreferenceStore(default_model=ModelName.CLAUDE),
        project_name=None,
        git_service=git_service,
        git_remote_name="origin",
        conversation_store=conversation_store,
        confirmation_store=InMemoryConfirmationStore(),
    )
    mgr = _bot_manager_for_project(
        project_registry,
        auth_service=AllowlistAuthService({123}),
        notifier=notifier,
        command_context=command_context,
    )
    app.include_router(
        create_webhook_router(
            bot_instance_manager=mgr,
            parser=CommandParser(
                project_registry=project_registry,
                default_model=ModelName.CLAUDE,
                conversation_store=conversation_store,
            ),
            command_registry=_commands_with_clear(),
            job_manager=job_manager,
            job_store=store,
            conversation_store=conversation_store,
        )
    )
    client = TestClient(app)
    wh = _webhook_url(project_registry)

    client.post(
        wh,
        json={
            "update_id": 40,
            "message": {
                "message_id": 40,
                "text": "plan: outline reply context",
                "chat": {"id": 123},
                "from": {"id": 999},
            },
        },
    )
    confirm_response = client.post(
        wh,
        json={
            "update_id": 41,
            "message": {"message_id": 41, "text": "y", "chat": {"id": 123}, "from": {"id": 999}},
        },
    )

    assert confirm_response.status_code == 200
    assert confirm_response.json()["status"] == "accepted"
    entries = conversation_store.list_recent("remote-coder", 123, 10)
    user_entries = [entry for entry in entries if entry.role == "user"]
    assert len(user_entries) == 1
    assert user_entries[0].message_id == 40
    assert user_entries[0].job_id == "job_1"


def test_webhook_slash_plan_requires_confirmation_then_accepts_y(project_registry):
    app = FastAPI()
    store = InMemoryJobStore()
    notifier = DummyNotifier()
    git_service = Mock()
    git_service.get_current_branch.return_value = "main"
    job_manager = CaptureJobManager()
    command_context = CommandContext(
        job_store=store,
        default_model=ModelName.CLAUDE,
        project_registry=project_registry,
        model_preferences=InMemoryModelPreferenceStore(default_model=ModelName.CLAUDE),
        project_name=None,
        git_service=git_service,
        git_remote_name="origin",
        conversation_store=None,
        confirmation_store=InMemoryConfirmationStore(),
    )
    mgr = _bot_manager_for_project(
        project_registry,
        auth_service=AllowlistAuthService({123}),
        notifier=notifier,
        command_context=command_context,
    )
    app.include_router(
        create_webhook_router(
            bot_instance_manager=mgr,
            parser=CommandParser(
                project_registry=project_registry,
                default_model=ModelName.CLAUDE,
            ),
            command_registry=_commands_with_clear(),
            job_manager=job_manager,
            job_store=store,
            conversation_store=None,
        )
    )
    client = TestClient(app)
    wh = _webhook_url(project_registry)
    response = client.post(
        wh,
        json={
            "update_id": 12,
            "message": {
                "message_id": 12,
                "text": "/plan model: codex outline only",
                "chat": {"id": 123},
                "from": {"id": 999},
            },
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json().get("job_id") is None
    pending = command_context.confirmation_store.get("remote-coder", 123)
    assert pending is not None
    assert pending.job_request.mode == JobMode.PLAN
    assert pending.job_request.model == ModelName.CODEX
    assert "outline only" in pending.job_request.instruction
    git_service.get_current_branch.assert_called_once()

    confirm_response = client.post(
        wh,
        json={
            "update_id": 13,
            "message": {"message_id": 13, "text": "Y", "chat": {"id": 123}, "from": {"id": 999}},
        },
    )
    assert confirm_response.status_code == 200
    assert confirm_response.json()["status"] == "accepted"
    assert job_manager.last_request.mode == JobMode.PLAN
    assert job_manager.last_request.model == ModelName.CODEX


def test_webhook_empty_slash_plan_waits_for_next_instruction(project_registry):
    app = FastAPI()
    store = InMemoryJobStore()
    notifier = DummyNotifier()
    git_service = Mock()
    git_service.get_current_branch.return_value = "main"
    job_manager = CaptureJobManager()
    command_context = CommandContext(
        job_store=store,
        default_model=ModelName.CLAUDE,
        project_registry=project_registry,
        model_preferences=InMemoryModelPreferenceStore(default_model=ModelName.CLAUDE),
        project_name=None,
        git_service=git_service,
        git_remote_name="origin",
        conversation_store=None,
        confirmation_store=InMemoryConfirmationStore(),
    )
    mgr = _bot_manager_for_project(
        project_registry,
        auth_service=AllowlistAuthService({123}),
        notifier=notifier,
        command_context=command_context,
    )
    app.include_router(
        create_webhook_router(
            bot_instance_manager=mgr,
            parser=CommandParser(
                project_registry=project_registry,
                default_model=ModelName.CLAUDE,
            ),
            command_registry=_commands_with_clear(),
            job_manager=job_manager,
            job_store=store,
            conversation_store=None,
        )
    )
    client = TestClient(app)
    wh = _webhook_url(project_registry)

    response = client.post(
        wh,
        json={
            "update_id": 120,
            "message": {"message_id": 120, "text": "/plan", "chat": {"id": 123}, "from": {"id": 999}},
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert "Send the instruction to run in plan mode" in notifier.sent[0][1]
    pending_input = command_context.confirmation_store.get("remote-coder", 123)
    assert pending_input is not None
    assert pending_input.action == JobMode.PLAN.value
    assert pending_input.job_request is None
    git_service.get_current_branch.assert_not_called()

    followup = client.post(
        wh,
        json={
            "update_id": 121,
            "message": {
                "message_id": 121,
                "text": "model: codex outline only",
                "chat": {"id": 123},
                "from": {"id": 999},
            },
        },
    )

    assert followup.status_code == 200
    assert followup.json()["status"] == "ok"
    pending = command_context.confirmation_store.get("remote-coder", 123)
    assert pending is not None
    assert pending.job_request is not None
    assert pending.job_request.mode == JobMode.PLAN
    assert pending.job_request.model == ModelName.CODEX
    assert pending.job_request.instruction == "outline only"
    assert pending.original_text == "model: codex outline only"
    assert "- Mode: plan" in notifier.sent[-1][1]
    git_service.get_current_branch.assert_called_once()


def test_webhook_empty_slash_ask_waits_for_next_instruction(project_registry):
    app = FastAPI()
    store = InMemoryJobStore()
    notifier = DummyNotifier()
    git_service = Mock()
    git_service.get_current_branch.return_value = "main"
    job_manager = CaptureJobManager()
    command_context = CommandContext(
        job_store=store,
        default_model=ModelName.CLAUDE,
        project_registry=project_registry,
        model_preferences=InMemoryModelPreferenceStore(default_model=ModelName.CLAUDE),
        project_name=None,
        git_service=git_service,
        git_remote_name="origin",
        conversation_store=None,
        confirmation_store=InMemoryConfirmationStore(),
    )
    mgr = _bot_manager_for_project(
        project_registry,
        auth_service=AllowlistAuthService({123}),
        notifier=notifier,
        command_context=command_context,
    )
    app.include_router(
        create_webhook_router(
            bot_instance_manager=mgr,
            parser=CommandParser(
                project_registry=project_registry,
                default_model=ModelName.CLAUDE,
            ),
            command_registry=_commands_with_clear(),
            job_manager=job_manager,
            job_store=store,
            conversation_store=None,
        )
    )
    client = TestClient(app)
    wh = _webhook_url(project_registry)

    response = client.post(
        wh,
        json={
            "update_id": 130,
            "message": {"message_id": 130, "text": "/ask", "chat": {"id": 123}, "from": {"id": 999}},
        },
    )
    followup = client.post(
        wh,
        json={
            "update_id": 131,
            "message": {
                "message_id": 131,
                "text": "what owns routing?",
                "chat": {"id": 123},
                "from": {"id": 999},
            },
        },
    )

    assert response.status_code == 200
    assert "Send the question to run in ask mode" in notifier.sent[0][1]
    assert followup.status_code == 200
    pending = command_context.confirmation_store.get("remote-coder", 123)
    assert pending is not None
    assert pending.job_request is not None
    assert pending.job_request.mode == JobMode.ASK
    assert "routing" in pending.job_request.instruction
    assert "- Mode: ask" in notifier.sent[-1][1]


def test_webhook_init_cancels_empty_slash_plan_wait(project_registry):
    app = FastAPI()
    store = InMemoryJobStore()
    notifier = DummyNotifier()
    git_service = Mock()
    job_manager = CaptureJobManager()
    command_context = CommandContext(
        job_store=store,
        default_model=ModelName.CLAUDE,
        project_registry=project_registry,
        model_preferences=InMemoryModelPreferenceStore(default_model=ModelName.CLAUDE),
        project_name=None,
        git_service=git_service,
        git_remote_name="origin",
        conversation_store=None,
        confirmation_store=InMemoryConfirmationStore(),
    )
    mgr = _bot_manager_for_project(
        project_registry,
        auth_service=AllowlistAuthService({123}),
        notifier=notifier,
        command_context=command_context,
    )
    app.include_router(
        create_webhook_router(
            bot_instance_manager=mgr,
            parser=CommandParser(
                project_registry=project_registry,
                default_model=ModelName.CLAUDE,
            ),
            command_registry=_commands_with_clear(),
            job_manager=job_manager,
            job_store=store,
            conversation_store=None,
        )
    )
    client = TestClient(app)
    wh = _webhook_url(project_registry)
    client.post(
        wh,
        json={
            "update_id": 140,
            "message": {"message_id": 140, "text": "/plan", "chat": {"id": 123}, "from": {"id": 999}},
        },
    )
    assert command_context.confirmation_store.get("remote-coder", 123) is not None

    response = client.post(
        wh,
        json={
            "update_id": 141,
            "message": {"message_id": 141, "text": "/init", "chat": {"id": 123}, "from": {"id": 999}},
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert command_context.confirmation_store.get("remote-coder", 123) is None
    assert "were reset" in notifier.sent[-1][1]


def test_webhook_ask_mode_requires_confirmation_then_accepts_y(project_registry):
    app = FastAPI()
    store = InMemoryJobStore()
    notifier = DummyNotifier()
    git_service = Mock()
    git_service.get_current_branch.return_value = "main"
    job_manager = CaptureJobManager()
    command_context = CommandContext(
        job_store=store,
        default_model=ModelName.CLAUDE,
        project_registry=project_registry,
        model_preferences=InMemoryModelPreferenceStore(default_model=ModelName.CLAUDE),
        project_name=None,
        git_service=git_service,
        git_remote_name="origin",
        conversation_store=None,
        confirmation_store=InMemoryConfirmationStore(),
    )
    mgr = _bot_manager_for_project(
        project_registry,
        auth_service=AllowlistAuthService({123}),
        notifier=notifier,
        command_context=command_context,
    )
    app.include_router(
        create_webhook_router(
            bot_instance_manager=mgr,
            parser=CommandParser(
                project_registry=project_registry,
                default_model=ModelName.CLAUDE,
            ),
            command_registry=_commands_with_clear(),
            job_manager=job_manager,
            job_store=store,
            conversation_store=None,
        )
    )
    client = TestClient(app)
    wh = _webhook_url(project_registry)
    response = client.post(
        wh,
        json={
            "update_id": 11,
            "message": {
                "message_id": 11,
                "text": "ASK: what owns routing?",
                "chat": {"id": 123},
                "from": {"id": 999},
            },
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json().get("job_id") is None
    pending = command_context.confirmation_store.get("remote-coder", 123)
    assert pending is not None
    assert pending.job_request.mode == JobMode.ASK
    assert "routing" in pending.job_request.instruction
    assert "- Mode: ask" in notifier.sent[0][1]
    git_service.get_current_branch.assert_called_once()

    confirm_response = client.post(
        wh,
        json={
            "update_id": 12,
            "message": {"message_id": 12, "text": "y", "chat": {"id": 123}, "from": {"id": 999}},
        },
    )
    assert confirm_response.status_code == 200
    assert confirm_response.json()["status"] == "accepted"
    assert job_manager.last_request.mode == JobMode.ASK


def test_webhook_natural_pending_replaced_silently_when_new_message_parses(project_registry):
    app = FastAPI()
    store = InMemoryJobStore()
    notifier = DummyNotifier()
    git_service = Mock()
    git_service.get_current_branch.return_value = "main"
    job_manager = CaptureJobManager()
    command_context = CommandContext(
        job_store=store,
        default_model=ModelName.CLAUDE,
        project_registry=project_registry,
        model_preferences=InMemoryModelPreferenceStore(default_model=ModelName.CLAUDE),
        project_name=None,
        git_service=git_service,
        git_remote_name="origin",
        conversation_store=None,
        confirmation_store=InMemoryConfirmationStore(),
    )
    mgr = _bot_manager_for_project(
        project_registry,
        auth_service=AllowlistAuthService({123}),
        notifier=notifier,
        command_context=command_context,
    )
    app.include_router(
        create_webhook_router(
            bot_instance_manager=mgr,
            parser=CommandParser(
                project_registry=project_registry,
                default_model=ModelName.CLAUDE,
            ),
            command_registry=_commands_with_clear(),
            job_manager=job_manager,
            job_store=store,
            conversation_store=None,
        )
    )
    client = TestClient(app)
    wh = _webhook_url(project_registry)
    client.post(
        wh,
        json={
            "update_id": 20,
            "message": {"message_id": 20, "text": "fix tests", "chat": {"id": 123}, "from": {"id": 999}},
        },
    )
    assert command_context.confirmation_store.get("remote-coder", 123) is not None
    assert not any(m[1].startswith("Cancelled the work request") for m in notifier.sent)

    replace = client.post(
        wh,
        json={
            "update_id": 21,
            "message": {
                "message_id": 21,
                "text": "plan: outline only",
                "chat": {"id": 123},
                "from": {"id": 999},
            },
        },
    )
    assert replace.status_code == 200
    assert replace.json()["status"] == "ok"
    assert not any(m[1].startswith("Cancelled the work request") for m in notifier.sent)
    pending = command_context.confirmation_store.get("remote-coder", 123)
    assert pending is not None
    assert pending.job_request is not None
    assert pending.job_request.mode == JobMode.PLAN
    assert "outline only" in pending.job_request.instruction
    assert notifier.sent[-1][1].count("- Mode: plan") >= 1

    confirm = client.post(
        wh,
        json={
            "update_id": 22,
            "message": {"message_id": 22, "text": "y", "chat": {"id": 123}, "from": {"id": 999}},
        },
    )
    assert confirm.json()["status"] == "accepted"
    assert job_manager.last_request is not None
    assert job_manager.last_request.mode == JobMode.PLAN


def test_webhook_natural_pending_parse_failure_sends_cancel_and_error(project_registry):
    app = FastAPI()
    store = InMemoryJobStore()
    notifier = DummyNotifier()
    git_service = Mock()
    git_service.get_current_branch.return_value = "main"
    command_context = CommandContext(
        job_store=store,
        default_model=ModelName.CLAUDE,
        project_registry=project_registry,
        model_preferences=InMemoryModelPreferenceStore(default_model=ModelName.CLAUDE),
        project_name=None,
        git_service=git_service,
        git_remote_name="origin",
        conversation_store=None,
        confirmation_store=InMemoryConfirmationStore(),
    )
    mgr = _bot_manager_for_project(
        project_registry,
        auth_service=AllowlistAuthService({123}),
        notifier=notifier,
        command_context=command_context,
    )
    app.include_router(
        create_webhook_router(
            bot_instance_manager=mgr,
            parser=CommandParser(
                project_registry=project_registry,
                default_model=ModelName.CLAUDE,
            ),
            command_registry=_commands_with_clear(),
            job_manager=DummyJobManager(),
            job_store=store,
            conversation_store=None,
        )
    )
    client = TestClient(app)
    wh = _webhook_url(project_registry)
    client.post(
        wh,
        json={
            "update_id": 30,
            "message": {"message_id": 30, "text": "fix tests", "chat": {"id": 123}, "from": {"id": 999}},
        },
    )
    fail = client.post(
        wh,
        json={
            "update_id": 31,
            "message": {"message_id": 31, "text": "plan:", "chat": {"id": 123}, "from": {"id": 999}},
        },
    )
    assert fail.status_code == 200
    assert fail.json()["status"] == "ignored"
    assert command_context.confirmation_store.get("remote-coder", 123) is None
    bodies = [m[1] for m in notifier.sent]
    assert any(t.startswith("Cancelled the work request") for t in bodies)
    assert any("The work instruction is empty" in t for t in bodies)


def test_webhook_accepts_natural_message_with_confirmation_buttons(project_registry):
    app = FastAPI()
    store = InMemoryJobStore()
    notifier = DummyNotifier()
    git_service = Mock()
    git_service.get_current_branch.return_value = "main"
    advanced_settings_store = Mock()
    advanced_settings_store.get.return_value = AdvancedSettings(
        ui_language="ko",
        natural_job_confirmation_buttons_enabled=True,
    )
    command_context = CommandContext(
        job_store=store,
        default_model=ModelName.CLAUDE,
        project_registry=project_registry,
        model_preferences=InMemoryModelPreferenceStore(default_model=ModelName.CLAUDE),
        project_name=None,
        git_service=git_service,
        git_remote_name="origin",
        conversation_store=None,
        confirmation_store=InMemoryConfirmationStore(),
        advanced_settings_store=advanced_settings_store,
    )
    mgr = _bot_manager_for_project(
        project_registry,
        auth_service=AllowlistAuthService({123}),
        notifier=notifier,
        command_context=command_context,
    )
    app.include_router(
        create_webhook_router(
            bot_instance_manager=mgr,
            parser=CommandParser(
                project_registry=project_registry,
                default_model=ModelName.CLAUDE,
            ),
            command_registry=_commands_with_clear(),
            job_manager=DummyJobManager(),
            job_store=store,
            conversation_store=None,
        )
    )
    client = TestClient(app)
    wh = _webhook_url(project_registry)

    response = client.post(
        wh,
        json={
            "update_id": 10,
            "message": {"message_id": 1, "text": "fix tests", "chat": {"id": 123}, "from": {"id": 999}},
        },
    )
    buttons = notifier.sent_with_buttons[0][2]
    confirm_response = client.post(
        wh,
        json={
            "update_id": 11,
            "callback_query": {
                "id": "cq_confirm_yes",
                "from": {"id": 999},
                "message": {"chat": {"id": 123}},
                "data": buttons[0][0].callback_data,
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert notifier.sent_with_buttons[0][1].startswith("Confirm the work to run.")
    assert "Choose whether to run it." in notifier.sent_with_buttons[0][1]
    assert buttons[0][0].label == "Yes"
    assert buttons[0][1].label == "No"
    assert confirm_response.status_code == 200
    assert confirm_response.json()["status"] == "accepted"
    assert "cq_confirm_yes" in notifier.answered_callbacks


def test_webhook_cancels_natural_message_with_confirmation_button(project_registry):
    app = FastAPI()
    store = InMemoryJobStore()
    notifier = DummyNotifier()
    git_service = Mock()
    git_service.get_current_branch.return_value = "main"
    advanced_settings_store = Mock()
    advanced_settings_store.get.return_value = AdvancedSettings(
        ui_language="ko",
        natural_job_confirmation_buttons_enabled=True,
    )
    command_context = CommandContext(
        job_store=store,
        default_model=ModelName.CLAUDE,
        project_registry=project_registry,
        model_preferences=InMemoryModelPreferenceStore(default_model=ModelName.CLAUDE),
        project_name=None,
        git_service=git_service,
        git_remote_name="origin",
        conversation_store=None,
        confirmation_store=InMemoryConfirmationStore(),
        advanced_settings_store=advanced_settings_store,
    )
    mgr = _bot_manager_for_project(
        project_registry,
        auth_service=AllowlistAuthService({123}),
        notifier=notifier,
        command_context=command_context,
    )
    app.include_router(
        create_webhook_router(
            bot_instance_manager=mgr,
            parser=CommandParser(
                project_registry=project_registry,
                default_model=ModelName.CLAUDE,
            ),
            command_registry=_commands_with_clear(),
            job_manager=DummyJobManager(),
            job_store=store,
            conversation_store=None,
        )
    )
    client = TestClient(app)
    wh = _webhook_url(project_registry)

    client.post(
        wh,
        json={
            "update_id": 12,
            "message": {"message_id": 1, "text": "fix tests", "chat": {"id": 123}, "from": {"id": 999}},
        },
    )
    buttons = notifier.sent_with_buttons[0][2]
    cancel_response = client.post(
        wh,
        json={
            "update_id": 13,
            "callback_query": {
                "id": "cq_confirm_no",
                "from": {"id": 999},
                "message": {"chat": {"id": 123}},
                "data": buttons[0][1].callback_data,
            },
        },
    )

    assert cancel_response.status_code == 200
    assert cancel_response.json()["status"] == "ok"
    assert notifier.sent[-1][1].startswith("Cancelled the work request.")
    assert "cq_confirm_no" in notifier.answered_callbacks


def test_webhook_sends_command_response_to_telegram(project_registry):
    app = FastAPI()
    store = InMemoryJobStore()
    notifier = DummyNotifier()
    command_context = CommandContext(
        job_store=store,
        default_model=ModelName.CLAUDE,
        project_registry=project_registry,
        model_preferences=InMemoryModelPreferenceStore(default_model=ModelName.CLAUDE),
        project_name=None,
        git_service=Mock(),
        git_remote_name="origin",
        conversation_store=None,
        confirmation_store=InMemoryConfirmationStore(),
    )
    mgr = _bot_manager_for_project(
        project_registry,
        auth_service=AllowlistAuthService({123}),
        notifier=notifier,
        command_context=command_context,
    )
    app.include_router(
        create_webhook_router(
            bot_instance_manager=mgr,
            parser=CommandParser(
                project_registry=project_registry,
                default_model=ModelName.CLAUDE,
            ),
            command_registry=_commands_with_clear(),
            job_manager=DummyJobManager(),
            job_store=store,
            conversation_store=None,
        )
    )
    client = TestClient(app)
    wh = _webhook_url(project_registry)
    payload = {
        "update_id": 1,
        "message": {"message_id": 1, "text": "/help", "chat": {"id": 123}, "from": {"id": 999}},
    }
    response = client.post(wh, json=payload)

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert notifier.sent_with_buttons
    assert notifier.sent_with_buttons[0][0] == 123


def test_webhook_executes_pending_clear_confirmation(project_registry):
    app = FastAPI()
    store = InMemoryJobStore()
    notifier = DummyNotifier()
    git_service = Mock()
    git_service.list_remote_branches_matching.return_value = ["remote-x"]
    git_service.list_local_branches_matching.return_value = ["remote-y"]
    command_context = CommandContext(
        job_store=store,
        default_model=ModelName.CLAUDE,
        project_registry=project_registry,
        model_preferences=InMemoryModelPreferenceStore(default_model=ModelName.CLAUDE),
        project_name=None,
        git_service=git_service,
        git_remote_name="origin",
        conversation_store=None,
        confirmation_store=InMemoryConfirmationStore(),
    )
    mgr = _bot_manager_for_project(
        project_registry,
        auth_service=AllowlistAuthService({123}),
        notifier=notifier,
        command_context=command_context,
    )
    app.include_router(
        create_webhook_router(
            bot_instance_manager=mgr,
            parser=CommandParser(
                project_registry=project_registry,
                default_model=ModelName.CLAUDE,
            ),
            command_registry=_commands_with_clear(),
            job_manager=DummyJobManager(),
            job_store=store,
            conversation_store=None,
        )
    )
    client = TestClient(app)
    wh = _webhook_url(project_registry)

    prompt_response = client.post(
        wh,
        json={
            "update_id": 10,
            "message": {"message_id": 10, "text": "/clear branch", "chat": {"id": 123}, "from": {"id": 999}},
        },
    )
    confirm_response = client.post(
        wh,
        json={
            "update_id": 11,
            "message": {"message_id": 11, "text": "Y", "chat": {"id": 123}, "from": {"id": 999}},
        },
    )

    assert prompt_response.status_code == 200
    assert prompt_response.json()["status"] == "ok"
    assert confirm_response.status_code == 200
    assert confirm_response.json()["status"] == "ok"
    assert "Pending action" in notifier.sent[0][1]
    assert "remote 1" in notifier.sent[1][1]


def test_webhook_executes_pending_clear_confirmation_with_buttons(project_registry):
    app = FastAPI()
    store = InMemoryJobStore()
    notifier = DummyNotifier()
    git_service = Mock()
    git_service.list_remote_branches_matching.return_value = ["remote-x"]
    git_service.list_local_branches_matching.return_value = ["remote-y"]
    advanced_settings_store = Mock()
    advanced_settings_store.get.return_value = AdvancedSettings(
        ui_language="ko",
        natural_job_confirmation_buttons_enabled=True,
    )
    command_context = CommandContext(
        job_store=store,
        default_model=ModelName.CLAUDE,
        project_registry=project_registry,
        model_preferences=InMemoryModelPreferenceStore(default_model=ModelName.CLAUDE),
        project_name=None,
        git_service=git_service,
        git_remote_name="origin",
        conversation_store=None,
        confirmation_store=InMemoryConfirmationStore(),
        advanced_settings_store=advanced_settings_store,
    )
    mgr = _bot_manager_for_project(
        project_registry,
        auth_service=AllowlistAuthService({123}),
        notifier=notifier,
        command_context=command_context,
    )
    app.include_router(
        create_webhook_router(
            bot_instance_manager=mgr,
            parser=CommandParser(
                project_registry=project_registry,
                default_model=ModelName.CLAUDE,
            ),
            command_registry=_commands_with_clear(),
            job_manager=DummyJobManager(),
            job_store=store,
            conversation_store=None,
        )
    )
    client = TestClient(app)
    wh = _webhook_url(project_registry)

    prompt_response = client.post(
        wh,
        json={
            "update_id": 10,
            "message": {"message_id": 10, "text": "/clear branch", "chat": {"id": 123}, "from": {"id": 999}},
        },
    )
    buttons = notifier.sent_with_buttons[0][2]
    confirm_response = client.post(
        wh,
        json={
            "update_id": 11,
            "callback_query": {
                "id": "cq_clear_confirm_yes",
                "from": {"id": 999},
                "message": {"chat": {"id": 123}},
                "data": buttons[0][0].callback_data,
            },
        },
    )

    assert prompt_response.status_code == 200
    assert prompt_response.json()["status"] == "ok"
    assert confirm_response.status_code == 200
    assert confirm_response.json()["status"] == "ok"
    assert notifier.sent_with_buttons[0][0] == 123
    assert "Choose whether to run it." in notifier.sent_with_buttons[0][1]
    assert buttons[0][0].label == "Yes"
    assert buttons[0][1].label == "No"
    assert "cq_clear_confirm_yes" in notifier.answered_callbacks
    assert "remote 1" in notifier.sent[0][1]


def test_webhook_executes_pending_clear_worktrees_confirmation(project_registry):
    app = FastAPI()
    store = InMemoryJobStore()
    notifier = DummyNotifier()
    git_service = Mock()
    git_service.cleanup_managed_worktrees.return_value = 3
    command_context = CommandContext(
        job_store=store,
        default_model=ModelName.CLAUDE,
        project_registry=project_registry,
        model_preferences=InMemoryModelPreferenceStore(default_model=ModelName.CLAUDE),
        project_name=None,
        git_service=git_service,
        git_remote_name="origin",
        conversation_store=None,
        confirmation_store=InMemoryConfirmationStore(),
    )
    mgr = _bot_manager_for_project(
        project_registry,
        auth_service=AllowlistAuthService({123}),
        notifier=notifier,
        command_context=command_context,
    )
    app.include_router(
        create_webhook_router(
            bot_instance_manager=mgr,
            parser=CommandParser(
                project_registry=project_registry,
                default_model=ModelName.CLAUDE,
            ),
            command_registry=_commands_with_clear(),
            job_manager=DummyJobManager(),
            job_store=store,
            conversation_store=None,
        )
    )
    client = TestClient(app)
    wh = _webhook_url(project_registry)

    prompt_response = client.post(
        wh,
        json={
            "update_id": 20,
            "message": {"message_id": 20, "text": "/clear worktrees", "chat": {"id": 123}, "from": {"id": 999}},
        },
    )
    confirm_response = client.post(
        wh,
        json={
            "update_id": 21,
            "message": {"message_id": 21, "text": "y", "chat": {"id": 123}, "from": {"id": 999}},
        },
    )

    assert prompt_response.status_code == 200
    assert prompt_response.json()["status"] == "ok"
    assert confirm_response.status_code == 200
    assert confirm_response.json()["status"] == "ok"
    assert "Pending action" in notifier.sent[0][1]
    assert "3 worktrees deleted" in notifier.sent[1][1]


def test_webhook_ambiguous_followup_uses_conversation_history(project_registry, tmp_path):
    db = tmp_path / "wh_conv.sqlite3"
    conv = SQLiteConversationStore(db)
    conv.append(
        project="remote-coder",
        chat_id=123,
        role="user",
        text="README에 한 줄 추가해줘",
        job_id=None,
    )
    parser = CommandParser(
        project_registry=project_registry,
        default_model=ModelName.CLAUDE,
        conversation_store=conv,
    )
    app = FastAPI()
    store = InMemoryJobStore()
    notifier = DummyNotifier()
    capture = CaptureJobManager()
    git_service = Mock()
    git_service.get_current_branch.return_value = "main"
    command_context = CommandContext(
        job_store=store,
        default_model=ModelName.CLAUDE,
        project_registry=project_registry,
        model_preferences=InMemoryModelPreferenceStore(default_model=ModelName.CLAUDE),
        project_name=None,
        git_service=git_service,
        git_remote_name="origin",
        conversation_store=conv,
        confirmation_store=InMemoryConfirmationStore(),
    )
    mgr = _bot_manager_for_project(
        project_registry,
        auth_service=AllowlistAuthService({123}),
        notifier=notifier,
        command_context=command_context,
    )
    app.include_router(
        create_webhook_router(
            bot_instance_manager=mgr,
            parser=parser,
            command_registry=_commands_with_clear(),
            job_manager=capture,
            job_store=store,
            conversation_store=conv,
        )
    )
    client = TestClient(app)
    wh = _webhook_url(project_registry)
    response = client.post(
        wh,
        json={
            "update_id": 2,
            "message": {"message_id": 2, "text": "작업 시작해줘", "chat": {"id": 123}, "from": {"id": 999}},
        },
    )
    confirm_response = client.post(
        wh,
        json={
            "update_id": 3,
            "message": {"message_id": 3, "text": "y", "chat": {"id": 123}, "from": {"id": 999}},
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert confirm_response.status_code == 200
    assert confirm_response.json()["status"] == "accepted"
    assert capture.last_request is not None
    assert "README" in capture.last_request.instruction


def test_webhook_ambiguous_without_history_sends_guidance(project_registry, tmp_path):
    db = tmp_path / "wh_empty.sqlite3"
    conv = SQLiteConversationStore(db)
    parser = CommandParser(
        project_registry=project_registry,
        default_model=ModelName.CLAUDE,
        conversation_store=conv,
    )
    app = FastAPI()
    store = InMemoryJobStore()
    notifier = DummyNotifier()
    command_context = CommandContext(
        job_store=store,
        default_model=ModelName.CLAUDE,
        project_registry=project_registry,
        model_preferences=InMemoryModelPreferenceStore(default_model=ModelName.CLAUDE),
        project_name=None,
        git_service=Mock(),
        git_remote_name="origin",
        conversation_store=conv,
        confirmation_store=InMemoryConfirmationStore(),
    )
    mgr = _bot_manager_for_project(
        project_registry,
        auth_service=AllowlistAuthService({123}),
        notifier=notifier,
        command_context=command_context,
    )
    app.include_router(
        create_webhook_router(
            bot_instance_manager=mgr,
            parser=parser,
            command_registry=_commands_with_clear(),
            job_manager=DummyJobManager(),
            job_store=store,
            conversation_store=conv,
        )
    )
    client = TestClient(app)
    wh = _webhook_url(project_registry)
    response = client.post(
        wh,
        json={
            "update_id": 3,
            "message": {"message_id": 3, "text": "진행해줘", "chat": {"id": 123}, "from": {"id": 999}},
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"
    assert notifier.sent
    assert "previous job context" in notifier.sent[0][1]


def test_webhook_conversation_isolated_by_chat(project_registry, tmp_path):
    db = tmp_path / "wh_iso.sqlite3"
    conv = SQLiteConversationStore(db)
    conv.append(project="remote-coder", chat_id=999, role="user", text="secret for 999", job_id=None)
    parser = CommandParser(
        project_registry=project_registry,
        default_model=ModelName.CLAUDE,
        conversation_store=conv,
    )
    app = FastAPI()
    store = InMemoryJobStore()
    notifier = DummyNotifier()
    capture = CaptureJobManager()
    git_service = Mock()
    git_service.get_current_branch.return_value = "main"
    command_context = CommandContext(
        job_store=store,
        default_model=ModelName.CLAUDE,
        project_registry=project_registry,
        model_preferences=InMemoryModelPreferenceStore(default_model=ModelName.CLAUDE),
        project_name=None,
        git_service=git_service,
        git_remote_name="origin",
        conversation_store=conv,
        confirmation_store=InMemoryConfirmationStore(),
    )
    mgr = _bot_manager_for_project(
        project_registry,
        auth_service=AllowlistAuthService({123, 999}),
        notifier=notifier,
        command_context=command_context,
    )
    app.include_router(
        create_webhook_router(
            bot_instance_manager=mgr,
            parser=parser,
            command_registry=_commands_with_clear(),
            job_manager=capture,
            job_store=store,
            conversation_store=conv,
        )
    )
    client = TestClient(app)
    wh = _webhook_url(project_registry)
    response = client.post(
        wh,
        json={
            "update_id": 4,
            "message": {"message_id": 4, "text": "작업 시작해줘", "chat": {"id": 123}, "from": {"id": 1}},
        },
    )
    assert response.json()["status"] == "ignored"
    assert "previous job context" in notifier.sent[-1][1]
    assert capture.last_request is None


def test_webhook_reply_reuses_bound_branch(project_registry, tmp_path):
    db = tmp_path / "wh_reply.sqlite3"
    conv = SQLiteConversationStore(db)
    conv.bind_message_branch(
        project="remote-coder",
        chat_id=123,
        message_id=1,
        branch="remote-a",
        job_id="job-1",
    )
    parser = CommandParser(
        project_registry=project_registry,
        default_model=ModelName.CLAUDE,
        conversation_store=conv,
    )
    app = FastAPI()
    store = InMemoryJobStore()
    notifier = DummyNotifier()
    capture = CaptureJobManager()
    command_context = CommandContext(
        job_store=store,
        default_model=ModelName.CLAUDE,
        project_registry=project_registry,
        model_preferences=InMemoryModelPreferenceStore(default_model=ModelName.CLAUDE),
        project_name=None,
        git_service=Mock(),
        git_remote_name="origin",
        conversation_store=conv,
        confirmation_store=InMemoryConfirmationStore(),
    )
    mgr = _bot_manager_for_project(
        project_registry,
        auth_service=AllowlistAuthService({123}),
        notifier=notifier,
        command_context=command_context,
    )
    app.include_router(
        create_webhook_router(
            bot_instance_manager=mgr,
            parser=parser,
            command_registry=_commands_with_clear(),
            job_manager=capture,
            job_store=store,
            conversation_store=conv,
        )
    )
    client = TestClient(app)
    wh = _webhook_url(project_registry)
    response = client.post(
        wh,
        json={
            "update_id": 5,
            "message": {
                "message_id": 2,
                "text": "추가 기능도 반영해줘",
                "chat": {"id": 123},
                "from": {"id": 999},
                "reply_to_message": {"message_id": 1},
            },
        },
    )
    confirm_response = client.post(
        wh,
        json={
            "update_id": 6,
            "message": {"message_id": 3, "text": "Y", "chat": {"id": 123}, "from": {"id": 999}},
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert confirm_response.status_code == 200
    assert confirm_response.json()["status"] == "accepted"
    assert capture.last_request is not None
    assert capture.last_request.branch == "remote-a"
    assert capture.last_request.reply_to_message_id == 1
    assert conv.get_bound_branch("remote-coder", 123, 2) == "remote-a"


def test_webhook_appends_user_message_with_telegram_ids(project_registry, tmp_path):
    db = tmp_path / "wh_msg_ids.sqlite3"
    conv = SQLiteConversationStore(db)
    parser = CommandParser(
        project_registry=project_registry,
        default_model=ModelName.CLAUDE,
        conversation_store=conv,
    )
    app = FastAPI()
    store = InMemoryJobStore()
    notifier = DummyNotifier()
    git_service = Mock()
    git_service.get_current_branch.return_value = "main"
    command_context = CommandContext(
        job_store=store,
        default_model=ModelName.CLAUDE,
        project_registry=project_registry,
        model_preferences=InMemoryModelPreferenceStore(default_model=ModelName.CLAUDE),
        project_name=None,
        git_service=git_service,
        git_remote_name="origin",
        conversation_store=conv,
        confirmation_store=InMemoryConfirmationStore(),
    )
    mgr = _bot_manager_for_project(
        project_registry,
        auth_service=AllowlistAuthService({123}),
        notifier=notifier,
        command_context=command_context,
    )
    app.include_router(
        create_webhook_router(
            bot_instance_manager=mgr,
            parser=parser,
            command_registry=_commands_with_clear(),
            job_manager=DummyJobManager(),
            job_store=store,
            conversation_store=conv,
        )
    )
    client = TestClient(app)
    wh = _webhook_url(project_registry)
    response = client.post(
        wh,
        json={
            "update_id": 50,
            "message": {
                "message_id": 77,
                "text": "hello worktree",
                "chat": {"id": 123},
                "from": {"id": 999},
                "reply_to_message": {"message_id": 66},
            },
        },
    )
    confirm_response = client.post(
        wh,
        json={
            "update_id": 51,
            "message": {"message_id": 78, "text": "y", "chat": {"id": 123}, "from": {"id": 999}},
        },
    )
    assert response.status_code == 200
    assert confirm_response.status_code == 200
    recent = conv.list_recent("remote-coder", 123, limit=5)
    user_rows = [e for e in recent if e.role == "user"]
    assert user_rows
    last_user = user_rows[-1]
    assert last_user.message_id == 77
    assert last_user.reply_to_message_id == 66


def test_webhook_records_bot_response_message_ids(project_registry, tmp_path):
    db = tmp_path / "wh_bot_msg_ids.sqlite3"
    conv = SQLiteConversationStore(db)
    parser = CommandParser(
        project_registry=project_registry,
        default_model=ModelName.CLAUDE,
        conversation_store=conv,
    )
    app = FastAPI()
    store = InMemoryJobStore()
    notifier = DummyNotifier()
    git_service = Mock()
    git_service.get_current_branch.return_value = "main"
    command_context = CommandContext(
        job_store=store,
        default_model=ModelName.CLAUDE,
        project_registry=project_registry,
        model_preferences=InMemoryModelPreferenceStore(default_model=ModelName.CLAUDE),
        project_name=None,
        git_service=git_service,
        git_remote_name="origin",
        conversation_store=conv,
        confirmation_store=InMemoryConfirmationStore(),
    )
    mgr = _bot_manager_for_project(
        project_registry,
        auth_service=AllowlistAuthService({123}),
        notifier=notifier,
        command_context=command_context,
    )
    job_manager = RecordedMessageJobManager()
    app.include_router(
        create_webhook_router(
            bot_instance_manager=mgr,
            parser=parser,
            command_registry=_commands_with_clear(),
            job_manager=job_manager,
            job_store=store,
            conversation_store=conv,
        )
    )
    client = TestClient(app)
    wh = _webhook_url(project_registry)
    client.post(
        wh,
        json={
            "update_id": 52,
            "message": {
                "message_id": 80,
                "text": "record bot replies",
                "chat": {"id": 123},
                "from": {"id": 999},
            },
        },
    )
    client.post(
        wh,
        json={
            "update_id": 53,
            "message": {"message_id": 81, "text": "y", "chat": {"id": 123}, "from": {"id": 999}},
        },
    )

    assert conv.get_job_id_for_message_id("remote-coder", 123, 200) == "job_recorded"
    assert conv.get_job_id_for_message_id("remote-coder", 123, 201) == "job_recorded"


def test_webhook_bare_fix_without_reply_requires_job_result_reply(project_registry, tmp_path):
    db = tmp_path / "wh_bare_fix_no_reply.sqlite3"
    conv = SQLiteConversationStore(db)
    parser = CommandParser(
        project_registry=project_registry,
        default_model=ModelName.CLAUDE,
        conversation_store=conv,
    )
    store = InMemoryJobStore()
    notifier = DummyNotifier()
    git_service = Mock()
    git_service.get_current_branch.return_value = "main"
    command_context = CommandContext(
        job_store=store,
        default_model=ModelName.CLAUDE,
        project_registry=project_registry,
        model_preferences=InMemoryModelPreferenceStore(default_model=ModelName.CLAUDE),
        project_name=None,
        git_service=git_service,
        git_remote_name="origin",
        conversation_store=conv,
        confirmation_store=InMemoryConfirmationStore(),
        job_manager=Mock(),
    )
    mgr = _bot_manager_for_project(
        project_registry,
        auth_service=AllowlistAuthService({123}),
        notifier=notifier,
        command_context=command_context,
    )
    app = FastAPI()
    app.include_router(
        create_webhook_router(
            bot_instance_manager=mgr,
            parser=parser,
            command_registry=_commands_with_clear(),
            job_manager=Mock(),
            job_store=store,
            conversation_store=conv,
        )
    )
    client = TestClient(app)
    wh = _webhook_url(project_registry)

    response = client.post(
        wh,
        json={
            "update_id": 80,
            "message": {"message_id": 90, "text": "/fix", "chat": {"id": 123}, "from": {"id": 999}},
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "ignored"
    assert any("replying to a job result" in text for _, text in notifier.sent)
    assert command_context.confirmation_store.get("remote-coder", 123) is None


def test_webhook_bare_fix_with_reply_stores_await_instruction(project_registry, tmp_path):
    from app.telegram.commands import FIX_SOURCE_AWAIT_ACTION

    db = tmp_path / "wh_bare_fix_reply.sqlite3"
    conv = SQLiteConversationStore(db)
    parser = CommandParser(
        project_registry=project_registry,
        default_model=ModelName.CLAUDE,
        conversation_store=conv,
    )
    store = InMemoryJobStore()
    parent_job = Job(
        id="parent_job",
        request=JobRequest(
            project="remote-coder",
            model=ModelName.CLAUDE,
            instruction="original work",
            chat_id=123,
            requested_by=999,
        ),
        status=JobStatus.SUCCEEDED,
        branch="remote-fix-1",
        commit_hash="abc1234",
    )
    store.create(parent_job)
    conv.append(
        project="remote-coder",
        chat_id=123,
        role="job_result",
        text="status=succeeded",
        job_id=parent_job.id,
        message_id=79,
    )

    fix_manager = Mock()
    fix_manager.resolve_fix_target_job.return_value = parent_job
    notifier = DummyNotifier()
    git_service = Mock()
    git_service.get_current_branch.return_value = "main"
    command_context = CommandContext(
        job_store=store,
        default_model=ModelName.CLAUDE,
        project_registry=project_registry,
        model_preferences=InMemoryModelPreferenceStore(default_model=ModelName.CLAUDE),
        project_name=None,
        git_service=git_service,
        git_remote_name="origin",
        conversation_store=conv,
        confirmation_store=InMemoryConfirmationStore(),
        job_manager=fix_manager,
    )
    mgr = _bot_manager_for_project(
        project_registry,
        auth_service=AllowlistAuthService({123}),
        notifier=notifier,
        command_context=command_context,
    )
    app = FastAPI()
    app.include_router(
        create_webhook_router(
            bot_instance_manager=mgr,
            parser=parser,
            command_registry=_commands_with_clear(),
            job_manager=fix_manager,
            job_store=store,
            conversation_store=conv,
        )
    )
    client = TestClient(app)
    wh = _webhook_url(project_registry)

    response = client.post(
        wh,
        json={
            "update_id": 81,
            "message": {
                "message_id": 91,
                "text": "/fix",
                "chat": {"id": 123},
                "from": {"id": 999},
                "reply_to_message": {"message_id": 79, "text": "Job done"},
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert any("fix instruction" in text.lower() for _, text in notifier.sent)
    pending = command_context.confirmation_store.get("remote-coder", 123)
    assert pending is not None
    assert pending.command_name == "/fix"
    assert pending.action == FIX_SOURCE_AWAIT_ACTION
    assert pending.target_job_id == parent_job.id
    assert pending.reply_to_message_id == 79


def test_webhook_fix_reply_queues_confirmation_and_executes(project_registry, tmp_path):
    from app.jobs.schemas import FixKind

    db = tmp_path / "wh_fix_reply.sqlite3"
    conv = SQLiteConversationStore(db)
    parser = CommandParser(
        project_registry=project_registry,
        default_model=ModelName.CLAUDE,
        conversation_store=conv,
    )
    store = InMemoryJobStore()
    parent_job = Job(
        id="parent_job",
        request=JobRequest(
            project="remote-coder",
            model=ModelName.CLAUDE,
            instruction="original work",
            chat_id=123,
            requested_by=999,
        ),
        status=JobStatus.SUCCEEDED,
        branch="remote-fix-1",
        commit_hash="abc1234",
        changed_files=["a.py"],
    )
    store.create(parent_job)
    conv.append(
        project="remote-coder",
        chat_id=123,
        role="job_result",
        text="status=succeeded",
        job_id=parent_job.id,
        message_id=79,
    )

    fix_manager = Mock()
    fix_manager.is_fix_candidate.return_value = True
    fix_manager.resolve_fix_target_job.return_value = parent_job
    fix_result = Job(
        id="fix_job",
        request=JobRequest(
            project="remote-coder",
            model=ModelName.CLAUDE,
            instruction="add tests",
            chat_id=123,
            requested_by=999,
            mode=JobMode.AGENT_FIX,
            fix_kind=FixKind.SOURCE,
            parent_job_id=parent_job.id,
            branch=parent_job.branch,
        ),
        status=JobStatus.SUCCEEDED,
        branch=parent_job.branch,
        commit_hash="def5678",
        result_message_ids=[202],
        accepted_message_id=201,
    )
    fix_manager.execute_fix_job.return_value = fix_result

    notifier = DummyNotifier()
    git_service = Mock()
    git_service.get_current_branch.return_value = "main"
    command_context = CommandContext(
        job_store=store,
        default_model=ModelName.CLAUDE,
        project_registry=project_registry,
        model_preferences=InMemoryModelPreferenceStore(default_model=ModelName.CLAUDE),
        project_name=None,
        git_service=git_service,
        git_remote_name="origin",
        conversation_store=conv,
        confirmation_store=InMemoryConfirmationStore(),
        job_manager=fix_manager,
    )
    mgr = _bot_manager_for_project(
        project_registry,
        auth_service=AllowlistAuthService({123}),
        notifier=notifier,
        command_context=command_context,
    )
    app = FastAPI()
    app.include_router(
        create_webhook_router(
            bot_instance_manager=mgr,
            parser=parser,
            command_registry=_commands_with_clear(),
            job_manager=fix_manager,
            job_store=store,
            conversation_store=conv,
        )
    )
    client = TestClient(app)
    wh = _webhook_url(project_registry)

    response = client.post(
        wh,
        json={
            "update_id": 70,
            "message": {
                "message_id": 80,
                "text": "fix: add tests",
                "chat": {"id": 123},
                "from": {"id": 999},
                "reply_to_message": {"message_id": 79, "text": "Job done parent_job"},
            },
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert any("Confirm the fix job" in text for _, text in notifier.sent)
    pending = command_context.confirmation_store.get("remote-coder", 123)
    assert pending is not None
    assert pending.job_request is not None
    assert pending.job_request.instruction == "add tests"
    assert pending.job_request.parent_job_id == parent_job.id

    confirm = client.post(
        wh,
        json={
            "update_id": 71,
            "message": {"message_id": 81, "text": "y", "chat": {"id": 123}, "from": {"id": 999}},
        },
    )
    assert confirm.status_code == 200
    assert confirm.json()["status"] == "accepted"
    fix_manager.execute_fix_job.assert_called_once()
    submitted = fix_manager.execute_fix_job.call_args.args[0]
    assert submitted.parent_job_id == parent_job.id
    assert submitted.instruction == "add tests"


def test_telegram_update_preserves_reply_message_text():
    update = TelegramUpdate.model_validate(
        {
            "update_id": 60,
            "message": {
                "message_id": 80,
                "text": "이 결과 기준으로 이어서 수정해줘",
                "chat": {"id": 123},
                "from": {"id": 999},
                "reply_to_message": {
                    "message_id": 79,
                    "text": "작업 완료\nJob ID: job_1\nAI 응답:\nREADME를 수정했습니다.",
                },
            },
        }
    )

    assert update.message is not None
    assert update.message.reply_to_message is not None
    assert update.message.reply_to_message.message_id == 79
    assert "README를 수정했습니다." in update.message.reply_to_message.text


def _make_webhook_app(project_registry, *, allowed_chats: set[int] | None = None, **kwargs):
    allowed = allowed_chats if allowed_chats is not None else {123}
    store = InMemoryJobStore()
    notifier = DummyNotifier()
    git_service = Mock()
    git_service.get_current_branch.return_value = "main"
    conv_store = kwargs.get("conversation_store")
    command_context = CommandContext(
        job_store=store,
        default_model=ModelName.CLAUDE,
        project_registry=project_registry,
        model_preferences=InMemoryModelPreferenceStore(default_model=ModelName.CLAUDE),
        project_name=None,
        git_service=git_service,
        git_remote_name="origin",
        conversation_store=conv_store,
        confirmation_store=InMemoryConfirmationStore(),
    )
    mgr = _bot_manager_for_project(
        project_registry,
        auth_service=AllowlistAuthService(allowed),
        notifier=notifier,
        command_context=command_context,
        webhook_secret=kwargs.get("webhook_secret"),
    )
    app = FastAPI()
    app.include_router(
        create_webhook_router(
            bot_instance_manager=mgr,
            parser=CommandParser(
                project_registry=project_registry,
                default_model=ModelName.CLAUDE,
            ),
            command_registry=_commands_with_clear(),
            job_manager=kwargs.get("job_manager", DummyJobManager()),
            job_store=store,
            conversation_store=conv_store,
        )
    )
    return TestClient(app), _webhook_url(project_registry)


def test_webhook_logs_inbound_and_job_accepted(caplog, project_registry):
    with caplog.at_level(logging.INFO):
        client, wh = _make_webhook_app(project_registry)
        client.post(
            wh,
            json={
                "update_id": 1,
                "message": {"message_id": 1, "text": "fix tests", "chat": {"id": 123}, "from": {"id": 999}},
            },
        )
        client.post(
            wh,
            json={
                "update_id": 2,
                "message": {"message_id": 2, "text": "y", "chat": {"id": 123}, "from": {"id": 999}},
            },
        )
    names = [r.name for r in caplog.records]
    assert "app.telegram.inbound" in names
    assert "app.telegram.command" in names
    assert any("received" in r.getMessage() for r in caplog.records)
    assert any("job accepted" in r.getMessage() for r in caplog.records)


def test_webhook_logs_auth_reject(caplog, project_registry):
    with caplog.at_level(logging.WARNING):
        client, wh = _make_webhook_app(project_registry, allowed_chats={123})
        client.post(
            wh,
            json={
                "update_id": 2,
                "message": {"message_id": 1, "text": "x", "chat": {"id": 999}, "from": {"id": 1}},
            },
        )
    assert any(r.name == "app.security.auth" for r in caplog.records)
    assert any("unauthorized" in r.getMessage() for r in caplog.records)


def test_webhook_logs_parse_error(caplog, project_registry):
    with caplog.at_level(logging.WARNING):
        client, wh = _make_webhook_app(project_registry)
        client.post(
            wh,
            json={
                "update_id": 3,
                "message": {"message_id": 1, "text": "   ", "chat": {"id": 123}, "from": {"id": 999}},
            },
        )
    assert any("parse error" in r.getMessage() for r in caplog.records)


def test_webhook_logs_secret_mismatch(caplog, project_registry):
    with caplog.at_level(logging.WARNING):
        client, wh = _make_webhook_app(project_registry, webhook_secret="expected")
        client.post(
            wh,
            json={
                "update_id": 4,
                "message": {"message_id": 1, "text": "hi", "chat": {"id": 123}, "from": {"id": 999}},
            },
            headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
        )
    assert any("secret mismatch" in r.getMessage() for r in caplog.records)


def test_webhook_callback_query_shows_detail_model_buttons(project_registry):
    app = FastAPI()
    store = InMemoryJobStore()
    notifier = DummyNotifier()
    command_context = CommandContext(
        job_store=store,
        default_model=ModelName.CLAUDE,
        project_registry=project_registry,
        model_preferences=InMemoryModelPreferenceStore(default_model=ModelName.CLAUDE),
        project_name=None,
        git_service=Mock(),
        git_remote_name="origin",
        conversation_store=None,
        confirmation_store=InMemoryConfirmationStore(),
    )
    mgr = _bot_manager_for_project(
        project_registry,
        auth_service=AllowlistAuthService({123}),
        notifier=notifier,
        command_context=command_context,
    )
    app.include_router(
        create_webhook_router(
            bot_instance_manager=mgr,
            parser=CommandParser(
                project_registry=project_registry,
                default_model=ModelName.CLAUDE,
            ),
            command_registry=CommandRegistry(
                [
                    HelpCommand(),
                    ModelCommand(),
                ]
            ),
            job_manager=DummyJobManager(),
            job_store=store,
            conversation_store=None,
        )
    )
    client = TestClient(app)
    wh = _webhook_url(project_registry)
    payload = {
        "update_id": 50,
        "callback_query": {
            "id": "cq_001",
            "from": {"id": 999},
            "message": {"chat": {"id": 123}},
            "data": "/model codex",
        },
    }
    response = client.post(wh, json=payload)
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert notifier.sent_with_buttons
    assert "Choose a specific model" in notifier.sent_with_buttons[0][1]
    buttons = notifier.sent_with_buttons[0][2]
    assert buttons[0][0].callback_data == "/model codex gpt-5.5"
    assert "cq_001" in notifier.answered_callbacks


def test_webhook_callback_query_confirms_detail_model(project_registry):
    app = FastAPI()
    store = InMemoryJobStore()
    notifier = DummyNotifier()
    model_preferences = InMemoryModelPreferenceStore(default_model=ModelName.CLAUDE)
    command_context = CommandContext(
        job_store=store,
        default_model=ModelName.CLAUDE,
        project_registry=project_registry,
        model_preferences=model_preferences,
        project_name=None,
        git_service=Mock(),
        git_remote_name="origin",
        conversation_store=None,
        confirmation_store=InMemoryConfirmationStore(),
    )
    mgr = _bot_manager_for_project(
        project_registry,
        auth_service=AllowlistAuthService({123}),
        notifier=notifier,
        command_context=command_context,
    )
    app.include_router(
        create_webhook_router(
            bot_instance_manager=mgr,
            parser=CommandParser(
                project_registry=project_registry,
                default_model=ModelName.CLAUDE,
            ),
            command_registry=CommandRegistry(
                [
                    HelpCommand(),
                    ModelCommand(),
                ]
            ),
            job_manager=DummyJobManager(),
            job_store=store,
            conversation_store=None,
        )
    )
    client = TestClient(app)
    payload = {
        "update_id": 53,
        "callback_query": {
            "id": "cq_model_detail",
            "from": {"id": 999},
            "message": {"chat": {"id": 123}},
            "data": "/model codex gpt-5.3-codex",
        },
    }

    response = client.post(_webhook_url(project_registry), json=payload)

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert notifier.sent == [(123, "Model setting updated.\n\n- Default model: codex / gpt-5.3-codex")]
    assert notifier.sent_with_buttons == []
    selection = model_preferences.get_explicit_selection("remote-coder", 123)
    assert selection is not None
    assert selection.provider == ModelName.CODEX
    assert selection.model_id == "gpt-5.3-codex"
    assert "cq_model_detail" in notifier.answered_callbacks


def test_webhook_callback_query_answers_before_command_execution(project_registry):
    app = FastAPI()
    store = InMemoryJobStore()
    notifier = DummyNotifier()
    command_context = CommandContext(
        job_store=store,
        default_model=ModelName.CLAUDE,
        project_registry=project_registry,
        model_preferences=InMemoryModelPreferenceStore(default_model=ModelName.CLAUDE),
        project_name=None,
        git_service=Mock(),
        git_remote_name="origin",
        conversation_store=None,
        confirmation_store=InMemoryConfirmationStore(),
    )

    class AckOrderCommand(TelegramCommand):
        name = "/ack-order"
        description = "ack order test"

        def execute(self, message, ctx) -> str:
            _ = (message, ctx)
            assert notifier.answered_callbacks == ["cq_order"]
            return "ack order ok"

    mgr = _bot_manager_for_project(
        project_registry,
        auth_service=AllowlistAuthService({123}),
        notifier=notifier,
        command_context=command_context,
    )
    app.include_router(
        create_webhook_router(
            bot_instance_manager=mgr,
            parser=CommandParser(
                project_registry=project_registry,
                default_model=ModelName.CLAUDE,
            ),
            command_registry=CommandRegistry([AckOrderCommand()]),
            job_manager=DummyJobManager(),
            job_store=store,
            conversation_store=None,
        )
    )
    client = TestClient(app)
    payload = {
        "update_id": 51,
        "callback_query": {
            "id": "cq_order",
            "from": {"id": 999},
            "message": {"chat": {"id": 123}},
            "data": "/ack-order",
        },
    }

    response = client.post(_webhook_url(project_registry), json=payload)

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert notifier.sent == [(123, "ack order ok")]


def test_recent_update_tracker_detects_duplicate_per_route_key():
    tracker = _RecentUpdateTracker(max_size=3)

    assert tracker.mark_seen("bot-a", 51) is False
    assert tracker.mark_seen("bot-a", 51) is True
    assert tracker.mark_seen("bot-b", 51) is False


def test_webhook_callback_query_sends_help_submenu_buttons(project_registry):
    app = FastAPI()
    store = InMemoryJobStore()
    notifier = DummyNotifier()
    command_context = CommandContext(
        job_store=store,
        default_model=ModelName.CLAUDE,
        project_registry=project_registry,
        model_preferences=InMemoryModelPreferenceStore(default_model=ModelName.CLAUDE),
        project_name=None,
        git_service=Mock(),
        git_remote_name="origin",
        conversation_store=None,
        confirmation_store=InMemoryConfirmationStore(),
    )
    mgr = _bot_manager_for_project(
        project_registry,
        auth_service=AllowlistAuthService({123}),
        notifier=notifier,
        command_context=command_context,
    )
    app.include_router(
        create_webhook_router(
            bot_instance_manager=mgr,
            parser=CommandParser(
                project_registry=project_registry,
                default_model=ModelName.CLAUDE,
            ),
            command_registry=CommandRegistry([HelpCommand(), ModelCommand()]),
            job_manager=DummyJobManager(),
            job_store=store,
            conversation_store=None,
        )
    )
    client = TestClient(app)
    wh = _webhook_url(project_registry)
    payload = {
        "update_id": 52,
        "callback_query": {
            "id": "cq_003",
            "from": {"id": 999},
            "message": {"chat": {"id": 123}},
            "data": "/help model",
        },
    }
    response = client.post(wh, json=payload)

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert notifier.sent_with_buttons
    assert notifier.sent_with_buttons[0][0] == 123
    assert notifier.sent_with_buttons[0][1] == "Choose a model."
    buttons = notifier.sent_with_buttons[0][2]
    assert buttons[0][0].callback_data == "/model claude"
    assert buttons[1][0].callback_data == "/help"
    assert "cq_003" in notifier.answered_callbacks


def test_webhook_unknown_token_hash_returns_404(project_registry):
    app = FastAPI()
    store = InMemoryJobStore()

    def _never_called(_: ProjectRecord) -> BotInstance:
        raise AssertionError("factory should not run when no bot is registered")

    mgr = BotInstanceManager(_never_called)
    app.include_router(
        create_webhook_router(
            bot_instance_manager=mgr,
            parser=CommandParser(
                project_registry=project_registry,
                default_model=ModelName.CLAUDE,
            ),
            command_registry=_commands_with_clear(),
            job_manager=DummyJobManager(),
            job_store=store,
            conversation_store=None,
        )
    )
    client = TestClient(app)
    response = client.post(
        "/telegram/webhook/" + "0" * 64,
        json={
            "update_id": 1,
            "message": {"message_id": 1, "text": "hi", "chat": {"id": 123}, "from": {"id": 999}},
        },
    )
    assert response.status_code == 404


def test_webhook_accepts_uppercase_hex_prefix(project_registry):
    client, wh = _make_webhook_app(project_registry)
    suffix = wh.removeprefix("/telegram/webhook/")
    upper_path = f"/telegram/webhook/{suffix.upper()}"
    response = client.post(
        upper_path,
        json={
            "update_id": 1,
            "message": {"message_id": 1, "text": "/help", "chat": {"id": 123}, "from": {"id": 999}},
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_webhook_rejects_full_sha256_path_length(project_registry):
    client, wh = _make_webhook_app(project_registry)
    suffix = wh.removeprefix("/telegram/webhook/")
    long_path = f"/telegram/webhook/{suffix}{'0' * 48}"
    response = client.post(
        long_path,
        json={
            "update_id": 1,
            "message": {"message_id": 1, "text": "/help", "chat": {"id": 123}, "from": {"id": 999}},
        },
    )
    assert response.status_code == 404


def test_webhook_rejects_invalid_hex_in_prefix(project_registry):
    client, _ = _make_webhook_app(project_registry)
    response = client.post(
        "/telegram/webhook/" + "0" * 15 + "g",
        json={
            "update_id": 1,
            "message": {"message_id": 1, "text": "/help", "chat": {"id": 123}, "from": {"id": 999}},
        },
    )
    assert response.status_code == 404


def test_webhook_callback_query_unauthorized_is_ignored(project_registry):
    app = FastAPI()
    store = InMemoryJobStore()
    notifier = DummyNotifier()
    command_context = CommandContext(
        job_store=store,
        default_model=ModelName.CLAUDE,
        project_registry=project_registry,
        model_preferences=InMemoryModelPreferenceStore(default_model=ModelName.CLAUDE),
        project_name=None,
        git_service=Mock(),
        git_remote_name="origin",
        conversation_store=None,
        confirmation_store=InMemoryConfirmationStore(),
    )
    mgr = _bot_manager_for_project(
        project_registry,
        auth_service=AllowlistAuthService({123}),
        notifier=notifier,
        command_context=command_context,
    )
    app.include_router(
        create_webhook_router(
            bot_instance_manager=mgr,
            parser=CommandParser(
                project_registry=project_registry,
                default_model=ModelName.CLAUDE,
            ),
            command_registry=CommandRegistry([ModelCommand()]),
            job_manager=DummyJobManager(),
            job_store=store,
            conversation_store=None,
        )
    )
    client = TestClient(app)
    wh = _webhook_url(project_registry)
    payload = {
        "update_id": 51,
        "callback_query": {
            "id": "cq_002",
            "from": {"id": 777},  # not in allowlist
            "message": {"chat": {"id": 999}},
            "data": "/model claude",
        },
    }
    response = client.post(wh, json=payload)
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"
    assert not notifier.sent
    assert "cq_002" in notifier.answered_callbacks
