import logging
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.admin.advanced_settings import AdvancedSettings
from app.jobs.plan_decisions import parse_plan_decisions
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
    InlineButton,
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
        self.edited: list[tuple[int, int, str, object]] = []
        self.answered_callbacks: list[str] = []
        self.answered_toasts: list[tuple[str, str | None, bool]] = []
        self.edit_returns: bool = True

    def send_text(self, chat_id: int, text: str, **kwargs) -> None:
        self.sent.append((chat_id, text))

    def send_with_buttons(self, chat_id: int, text: str, inline_buttons, **kwargs) -> None:
        self.sent_with_buttons.append((chat_id, text, inline_buttons))

    def edit_message(self, chat_id: int, message_id: int, text: str, inline_buttons, **kwargs) -> bool:
        self.edited.append((chat_id, message_id, text, inline_buttons))
        return self.edit_returns

    def send_long_text(self, chat_id: int, text: str) -> list[int]:
        self.sent.append((chat_id, text))
        return [1]

    def answer_callback_query(self, callback_query_id: str, *, text=None, show_alert: bool = False) -> None:
        self.answered_callbacks.append(callback_query_id)
        self.answered_toasts.append((callback_query_id, text, show_alert))


def _confirm_via_button(client, wh, notifier, update_id, *, message_id=900, yes=True):
    """Tap the Yes (or No) button of the most recent buttoned confirmation."""
    buttons = notifier.sent_with_buttons[-1][2]
    data = buttons[0][0].callback_data if yes else buttons[0][1].callback_data
    return client.post(
        wh,
        json={
            "update_id": update_id,
            "callback_query": {
                "id": f"cq_{update_id}",
                "from": {"id": 999},
                "message": {"chat": {"id": 123}, "message_id": message_id},
                "data": data,
            },
        },
    )


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
    confirm_response = _confirm_via_button(client, wh, notifier, 2)
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    conf_text = notifier.sent_with_buttons[0][1]
    assert conf_text.startswith("Confirm the work to run.")
    assert "- Project: remote-coder" in conf_text
    assert "- Work branch: main" in conf_text
    assert "- Model: claude" in conf_text
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
    assert "- Mode: plan" in notifier.sent_with_buttons[0][1]
    git_service.get_current_branch.assert_called_once()

    confirm_response = _confirm_via_button(client, wh, notifier, 11)
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
    confirm_response = _confirm_via_button(client, wh, notifier, 41)

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

    confirm_response = _confirm_via_button(client, wh, notifier, 13)
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
    assert "- Mode: plan" in notifier.sent_with_buttons[-1][1]
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
    assert "- Mode: ask" in notifier.sent_with_buttons[-1][1]


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
    assert "- Mode: ask" in notifier.sent_with_buttons[0][1]
    git_service.get_current_branch.assert_called_once()

    confirm_response = _confirm_via_button(client, wh, notifier, 12)
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
    assert notifier.sent_with_buttons[-1][1].count("- Mode: plan") >= 1

    confirm = _confirm_via_button(client, wh, notifier, 22)
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
    confirm_response = _confirm_via_button(client, wh, notifier, 11)

    assert prompt_response.status_code == 200
    assert prompt_response.json()["status"] == "ok"
    assert confirm_response.status_code == 200
    assert confirm_response.json()["status"] == "ok"
    assert "Pending action" in notifier.sent_with_buttons[0][1]
    assert "remote 1" in notifier.sent[0][1]


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
    confirm_response = _confirm_via_button(client, wh, notifier, 21)

    assert prompt_response.status_code == 200
    assert prompt_response.json()["status"] == "ok"
    assert confirm_response.status_code == 200
    assert confirm_response.json()["status"] == "ok"
    assert "Pending action" in notifier.sent_with_buttons[0][1]
    assert "3 worktrees deleted" in notifier.sent[0][1]


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
    confirm_response = _confirm_via_button(client, wh, notifier, 3)
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
    confirm_response = _confirm_via_button(client, wh, notifier, 6)

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
    confirm_response = _confirm_via_button(client, wh, notifier, 51)
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
    _confirm_via_button(client, wh, notifier, 53)

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
    assert any("Confirm the fix job" in m[1] for m in notifier.sent_with_buttons)
    pending = command_context.confirmation_store.get("remote-coder", 123)
    assert pending is not None
    assert pending.job_request is not None
    assert pending.job_request.instruction == "add tests"
    assert pending.job_request.parent_job_id == parent_job.id

    confirm = _confirm_via_button(client, wh, notifier, 71)
    assert confirm.status_code == 200
    assert confirm.json()["status"] == "accepted"
    fix_manager.execute_fix_job.assert_called_once()
    submitted = fix_manager.execute_fix_job.call_args.args[0]
    assert submitted.parent_job_id == parent_job.id
    assert submitted.instruction == "add tests"
    assert submitted.session_id is not None


def test_webhook_fix_reply_to_job_result_reuses_parent_session(project_registry, tmp_path):
    from app.jobs.schemas import FixKind

    db = tmp_path / "wh_fix_reply_session.sqlite3"
    conv = SQLiteConversationStore(db)
    parser = CommandParser(
        project_registry=project_registry,
        default_model=ModelName.CLAUDE,
        conversation_store=conv,
    )
    store = InMemoryJobStore()
    parent_session = conv.resolve_or_create_session("remote-coder", 123, 40, None)
    conv.set_runner_resume_token(parent_session, ModelName.CLAUDE.value, "runner-parent")
    parent_job = Job(
        id="parent_job",
        request=JobRequest(
            project="remote-coder",
            model=ModelName.CLAUDE,
            instruction="original work",
            chat_id=123,
            requested_by=999,
            message_id=40,
            session_id=parent_session,
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
        role="user",
        text="original work",
        job_id=parent_job.id,
        message_id=40,
    )
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

    def _execute_fix_job(request):
        return Job(
            id="fix_job",
            request=request,
            status=JobStatus.SUCCEEDED,
            branch=parent_job.branch,
            commit_hash="def5678",
            result_message_ids=[202],
            accepted_message_id=201,
        )

    fix_manager.execute_fix_job.side_effect = _execute_fix_job

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
            "update_id": 72,
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

    confirm = _confirm_via_button(client, wh, notifier, 73)
    assert confirm.status_code == 200
    assert confirm.json()["status"] == "accepted"
    fix_manager.execute_fix_job.assert_called_once()
    submitted = fix_manager.execute_fix_job.call_args.args[0]
    assert submitted.session_id == parent_session
    assert submitted.resume_session_token == "runner-parent"


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
                "callback_query": {
                    "id": "cq_accept",
                    "from": {"id": 999},
                    "message": {"chat": {"id": 123}, "message_id": 2},
                    "data": "__natural_job__:yes",
                },
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


def test_webhook_callback_query_answers_within_request(project_registry):
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
    assert notifier.answered_callbacks == ["cq_order"]
    assert notifier.sent == [(123, "ack order ok")]


def _editable_panel_app(project_registry, notifier, commands):
    app = FastAPI()
    store = InMemoryJobStore()
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
            parser=CommandParser(project_registry=project_registry, default_model=ModelName.CLAUDE),
            command_registry=CommandRegistry(commands),
            job_manager=DummyJobManager(),
            job_store=store,
            conversation_store=None,
        )
    )
    return app


def _panel_command():
    class PanelCommand(TelegramCommand):
        name = "/panel"
        description = "panel"

        def execute(self, message, ctx) -> str:
            return "Menu"

        def get_inline_buttons(self, message=None, ctx=None):
            return [[InlineButton("Go", "/panel")]]

    return PanelCommand()


def test_webhook_callback_navigation_edits_in_place(project_registry):
    notifier = DummyNotifier()
    app = _editable_panel_app(project_registry, notifier, [_panel_command()])
    client = TestClient(app)
    client.post(
        _webhook_url(project_registry),
        json={
            "update_id": 60,
            "callback_query": {
                "id": "cq_nav",
                "from": {"id": 999},
                "message": {"chat": {"id": 123}, "message_id": 555},
                "data": "/panel",
            },
        },
    )
    assert notifier.edited and notifier.edited[0][:3] == (123, 555, "Menu")
    assert notifier.sent_with_buttons == []
    assert "cq_nav" in notifier.answered_callbacks


def test_webhook_callback_navigation_falls_back_to_send_when_edit_fails(project_registry):
    notifier = DummyNotifier()
    notifier.edit_returns = False
    app = _editable_panel_app(project_registry, notifier, [_panel_command()])
    client = TestClient(app)
    client.post(
        _webhook_url(project_registry),
        json={
            "update_id": 61,
            "callback_query": {
                "id": "cq_nav2",
                "from": {"id": 999},
                "message": {"chat": {"id": 123}, "message_id": 556},
                "data": "/panel",
            },
        },
    )
    assert notifier.edited  # edit attempted
    assert notifier.sent_with_buttons and notifier.sent_with_buttons[0][1] == "Menu"


def test_webhook_callback_terminal_text_sends_new_with_toast(project_registry):
    class LeafCommand(TelegramCommand):
        name = "/leaf"
        description = "leaf"

        def execute(self, message, ctx) -> str:
            return "Done line\nmore detail"

    notifier = DummyNotifier()
    app = _editable_panel_app(project_registry, notifier, [LeafCommand()])
    client = TestClient(app)
    client.post(
        _webhook_url(project_registry),
        json={
            "update_id": 62,
            "callback_query": {
                "id": "cq_leaf",
                "from": {"id": 999},
                "message": {"chat": {"id": 123}, "message_id": 557},
                "data": "/leaf",
            },
        },
    )
    assert notifier.edited == []
    assert notifier.sent == [(123, "Done line\nmore detail")]
    assert notifier.answered_toasts[-1][1] == "Done line"


def test_webhook_callback_close_panel_clears_keyboard(project_registry):
    notifier = DummyNotifier()
    app = _editable_panel_app(project_registry, notifier, [_panel_command()])
    client = TestClient(app)
    client.post(
        _webhook_url(project_registry),
        json={
            "update_id": 63,
            "callback_query": {
                "id": "cq_close",
                "from": {"id": 999},
                "message": {"chat": {"id": 123}, "message_id": 558},
                "data": "__close__",
            },
        },
    )
    assert notifier.edited and notifier.edited[0] == (123, 558, "Closed.", [])
    assert "cq_close" in notifier.answered_callbacks


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


class SessionRecordingJobManager:
    def __init__(self, branch: str, runner_session_id: str) -> None:
        self.requests: list[JobRequest] = []
        self.branch = branch
        self.runner_session_id = runner_session_id

    def submit(self, request):
        self.requests.append(request)
        return Job(id=f"job_{len(self.requests)}", request=request, accepted_message_id=200)

    def run(self, job_id: str):
        request = self.requests[-1]
        return Job(
            id=job_id,
            request=request,
            status=JobStatus.SUCCEEDED,
            branch=self.branch,
            commit_hash="abc1234",
            runner_session_id=self.runner_session_id,
            result_message_ids=[201],
        )


def test_webhook_reply_jobs_share_session_and_resume(project_registry, tmp_path):
    app = FastAPI()
    store = InMemoryJobStore()
    conversation_store = SQLiteConversationStore(tmp_path / "conv.sqlite3")
    notifier = DummyNotifier()
    git_service = Mock()
    git_service.get_current_branch.return_value = "main"
    git_service.local_branch_exists.return_value = True
    runner_session = "11111111-1111-1111-1111-111111111111"
    job_manager = SessionRecordingJobManager(branch="remote-x", runner_session_id=runner_session)
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
                "text": "build the feature",
                "chat": {"id": 123},
                "from": {"id": 999},
            },
        },
    )
    _confirm_via_button(client, wh, notifier, 41)

    # First (root) job establishes a session id but has nothing to resume yet.
    root_request = job_manager.requests[0]
    assert root_request.session_id is not None
    assert root_request.resume_session_token is None

    client.post(
        wh,
        json={
            "update_id": 42,
            "message": {
                "message_id": 42,
                "text": "now extend it",
                "chat": {"id": 123},
                "from": {"id": 999},
                "reply_to_message": {"message_id": 40, "text": "build the feature"},
            },
        },
    )
    _confirm_via_button(client, wh, notifier, 43, message_id=901)

    reply_request = job_manager.requests[1]
    assert reply_request.session_id == root_request.session_id
    assert reply_request.resume_session_token == runner_session


_DECISION_BLOCK = (
    "```plan-decisions\n"
    '{"questions": ['
    '{"id": "db", "header": "DB", "question": "Which database?", "options": ['
    '{"label": "PostgreSQL", "description": "Relational"}, '
    '{"label": "SQLite", "description": "File based"}]}, '
    '{"id": "scope", "header": "Scope", "question": "Reuse module?", "options": ['
    '{"label": "Reuse", "description": "Extend existing"}, '
    '{"label": "New", "description": "Create new"}]}'
    "]}\n"
    "```"
)


def _build_plan_decision_app(project_registry, notifier, job_manager):
    app = FastAPI()
    store = InMemoryJobStore()
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
            job_manager=job_manager,
            job_store=store,
            conversation_store=None,
        )
    )
    return app, command_context


def _plan_job_for_decisions():
    return Job(
        id="job_plan_a",
        request=JobRequest(
            project="remote-coder",
            model=ModelName.CLAUDE,
            instruction="plan the storage layer",
            mode=JobMode.PLAN,
            chat_id=123,
            requested_by=999,
        ),
    )


def _tap_decision(client, wh, notifier, update_id, option_index):
    rows = notifier.sent_with_buttons[-1][2]
    data = rows[option_index][0].callback_data
    return client.post(
        wh,
        json={
            "update_id": update_id,
            "callback_query": {
                "id": f"cq_{update_id}",
                "from": {"id": 999},
                "message": {"chat": {"id": 123}, "message_id": 900 + update_id},
                "data": data,
            },
        },
    )


def test_plan_decisions_flow_asks_then_submits_phase_b(project_registry):
    notifier = DummyNotifier()
    job_manager = CaptureJobManager()
    app, _ = _build_plan_decision_app(project_registry, notifier, job_manager)
    client = TestClient(app)
    wh = _webhook_url(project_registry)

    questions = parse_plan_decisions(_DECISION_BLOCK)
    assert questions is not None
    # Simulate the JobManager background thread surfacing decisions from phase A.
    assert job_manager.plan_decision_router(_plan_job_for_decisions(), questions) is True

    assert len(notifier.sent_with_buttons) == 1
    first_text = notifier.sent_with_buttons[0][1]
    assert "Decision 1/2" in first_text
    assert "Which database?" in first_text

    first = _tap_decision(client, wh, notifier, 1, option_index=0)
    assert first.json()["status"] == "ok"
    assert len(notifier.sent_with_buttons) == 2
    assert "Decision 2/2" in notifier.sent_with_buttons[1][1]
    assert "Reuse module?" in notifier.sent_with_buttons[1][1]
    assert job_manager.last_request is None

    second = _tap_decision(client, wh, notifier, 2, option_index=1)
    assert second.json()["status"] == "accepted"

    submitted = job_manager.last_request
    assert submitted is not None
    assert submitted.mode == JobMode.PLAN
    assert submitted.plan_decisions_resolved is True
    assert "PostgreSQL" in submitted.instruction
    assert "New" in submitted.instruction
    assert "plan the storage layer" in submitted.instruction


def test_plan_decisions_stale_tap_is_ignored(project_registry):
    notifier = DummyNotifier()
    job_manager = CaptureJobManager()
    app, _ = _build_plan_decision_app(project_registry, notifier, job_manager)
    client = TestClient(app)
    wh = _webhook_url(project_registry)

    questions = parse_plan_decisions(_DECISION_BLOCK)
    job_manager.plan_decision_router(_plan_job_for_decisions(), questions)

    # Answer question 1, then re-tap the (now stale) question-1 button again.
    rows_q1 = notifier.sent_with_buttons[0][2]
    stale_data = rows_q1[0][0].callback_data
    _tap_decision(client, wh, notifier, 1, option_index=0)
    before = len(notifier.sent_with_buttons)
    resp = client.post(
        wh,
        json={
            "update_id": 5,
            "callback_query": {
                "id": "cq_stale",
                "from": {"id": 999},
                "message": {"chat": {"id": 123}, "message_id": 950},
                "data": stale_data,
            },
        },
    )
    assert resp.json()["status"] == "ignored"
    assert len(notifier.sent_with_buttons) == before
    assert job_manager.last_request is None


def test_plan_decisions_cancelled_by_typed_message(project_registry):
    notifier = DummyNotifier()
    job_manager = CaptureJobManager()
    app, _ = _build_plan_decision_app(project_registry, notifier, job_manager)
    client = TestClient(app)
    wh = _webhook_url(project_registry)

    questions = parse_plan_decisions(_DECISION_BLOCK)
    job_manager.plan_decision_router(_plan_job_for_decisions(), questions)

    client.post(
        wh,
        json={
            "update_id": 7,
            "message": {
                "message_id": 7,
                "text": "never mind",
                "chat": {"id": 123},
                "from": {"id": 999},
            },
        },
    )
    assert any("Cancelled the pending plan decision." in text for _, text in notifier.sent)
    # A later decision tap finds no pending state.
    rows = notifier.sent_with_buttons[0][2]
    resp = client.post(
        wh,
        json={
            "update_id": 8,
            "callback_query": {
                "id": "cq_after_cancel",
                "from": {"id": 999},
                "message": {"chat": {"id": 123}, "message_id": 960},
                "data": rows[0][0].callback_data,
            },
        },
    )
    assert resp.json()["status"] == "ignored"


def _build_plan_exec_app(project_registry, notifier, job_manager, store):
    app = FastAPI()
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
            parser=CommandParser(project_registry=project_registry, default_model=ModelName.CLAUDE),
            command_registry=_commands_with_clear(),
            job_manager=job_manager,
            job_store=store,
            conversation_store=None,
        )
    )
    return app


def _seed_plan_job(store, *, status=JobStatus.SUCCEEDED, chat_id=123, project="remote-coder", mode=JobMode.PLAN):
    job = Job(
        id="job_plan_x",
        request=JobRequest(
            project=project,
            model=ModelName.CLAUDE,
            instruction="plan the storage layer",
            mode=mode,
            chat_id=chat_id,
            requested_by=999,
        ),
        status=status,
        runner_stdout_summary="1. add Store class\n2. wire it",
    )
    store.create(job)
    return job


def _tap_exec(client, wh, update_id, job_id="job_plan_x"):
    return client.post(
        wh,
        json={
            "update_id": update_id,
            "callback_query": {
                "id": f"cq_{update_id}",
                "from": {"id": 999},
                "message": {"chat": {"id": 123}, "message_id": 800 + update_id},
                "data": f"__plan_exec__:{job_id}",
            },
        },
    )


def test_plan_execute_button_submits_agent_job(project_registry):
    notifier = DummyNotifier()
    job_manager = CaptureJobManager()
    store = InMemoryJobStore()
    _seed_plan_job(store)
    app = _build_plan_exec_app(project_registry, notifier, job_manager, store)
    client = TestClient(app)
    wh = _webhook_url(project_registry)

    resp = _tap_exec(client, wh, 1)
    assert resp.json()["status"] == "accepted"
    submitted = job_manager.last_request
    assert submitted is not None
    assert submitted.mode == JobMode.AGENT
    assert submitted.parent_job_id == "job_plan_x"
    assert "add Store class" in submitted.instruction
    assert "plan the storage layer" in submitted.instruction


def test_plan_execute_double_tap_ignored(project_registry):
    notifier = DummyNotifier()
    job_manager = CaptureJobManager()
    store = InMemoryJobStore()
    _seed_plan_job(store)
    app = _build_plan_exec_app(project_registry, notifier, job_manager, store)
    client = TestClient(app)
    wh = _webhook_url(project_registry)

    assert _tap_exec(client, wh, 1).json()["status"] == "accepted"
    job_manager.last_request = None
    second = _tap_exec(client, wh, 2)
    assert second.json()["status"] == "ignored"
    assert job_manager.last_request is None


def test_plan_execute_rejects_non_succeeded_plan(project_registry):
    notifier = DummyNotifier()
    job_manager = CaptureJobManager()
    store = InMemoryJobStore()
    _seed_plan_job(store, status=JobStatus.FAILED)
    app = _build_plan_exec_app(project_registry, notifier, job_manager, store)
    client = TestClient(app)
    wh = _webhook_url(project_registry)

    resp = _tap_exec(client, wh, 1)
    assert resp.json()["status"] == "ignored"
    assert job_manager.last_request is None
    assert any("can no longer be run" in text for _, text in notifier.sent)


def test_plan_execute_unknown_job_ignored(project_registry):
    notifier = DummyNotifier()
    job_manager = CaptureJobManager()
    store = InMemoryJobStore()
    app = _build_plan_exec_app(project_registry, notifier, job_manager, store)
    client = TestClient(app)
    wh = _webhook_url(project_registry)

    resp = _tap_exec(client, wh, 1, job_id="job_missing")
    assert resp.json()["status"] == "ignored"
    assert job_manager.last_request is None


def _build_session_app(project_registry, notifier, job_manager, conversation_store, store=None):
    app = FastAPI()
    store = store if store is not None else InMemoryJobStore()
    git_service = Mock()
    git_service.get_current_branch.return_value = "main"
    git_service.local_branch_exists.return_value = False
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
    return app, store


def test_webhook_ask_reply_chain_reuses_session_without_branch(project_registry, tmp_path):
    # PLAN/ASK runs never bind a branch (they are read-only), so before the fix the resume
    # token was discarded on the reply and every follow-up ate a fresh provider session.
    conversation_store = SQLiteConversationStore(tmp_path / "ask.sqlite3")
    notifier = DummyNotifier()
    runner_session = "11111111-1111-1111-1111-111111111111"
    job_manager = SessionRecordingJobManager(branch=None, runner_session_id=runner_session)
    app, _ = _build_session_app(project_registry, notifier, job_manager, conversation_store)
    client = TestClient(app)
    wh = _webhook_url(project_registry)

    client.post(
        wh,
        json={
            "update_id": 50,
            "message": {
                "message_id": 50,
                "text": "/ask explain the JobManager flow",
                "chat": {"id": 123},
                "from": {"id": 999},
            },
        },
    )
    _confirm_via_button(client, wh, notifier, 51, message_id=901)

    root_request = job_manager.requests[0]
    assert root_request.mode == JobMode.ASK
    assert root_request.branch is None
    assert root_request.session_id is not None
    assert root_request.resume_session_token is None

    client.post(
        wh,
        json={
            "update_id": 52,
            "message": {
                "message_id": 52,
                "text": "/ask and where does it commit?",
                "chat": {"id": 123},
                "from": {"id": 999},
                "reply_to_message": {"message_id": 50, "text": "/ask explain the JobManager flow"},
            },
        },
    )
    _confirm_via_button(client, wh, notifier, 53, message_id=902)

    reply_request = job_manager.requests[1]
    assert reply_request.mode == JobMode.ASK
    assert reply_request.branch is None
    assert reply_request.session_id == root_request.session_id
    assert reply_request.resume_session_token == runner_session


def test_plan_phase_b_inherits_session_and_resume_token(project_registry, tmp_path):
    conversation_store = SQLiteConversationStore(tmp_path / "phaseb.sqlite3")
    session_id = conversation_store.resolve_or_create_session("remote-coder", 123, 40, None)
    conversation_store.set_runner_resume_token(session_id, ModelName.CLAUDE.value, "runner-tok-A")

    notifier = DummyNotifier()
    job_manager = CaptureJobManager()
    app, _ = _build_session_app(project_registry, notifier, job_manager, conversation_store)
    client = TestClient(app)
    wh = _webhook_url(project_registry)

    plan_a_request = JobRequest(
        project="remote-coder",
        model=ModelName.CLAUDE,
        instruction="plan the storage layer",
        mode=JobMode.PLAN,
        chat_id=123,
        requested_by=999,
        message_id=40,
        session_id=session_id,
    )
    plan_a_job = Job(id="job_plan_a", request=plan_a_request)

    questions = parse_plan_decisions(_DECISION_BLOCK)
    assert questions is not None
    assert job_manager.plan_decision_router(plan_a_job, questions) is True

    _tap_decision(client, wh, notifier, 1, option_index=0)
    _tap_decision(client, wh, notifier, 2, option_index=1)

    phase_b = job_manager.last_request
    assert phase_b is not None
    assert phase_b.mode == JobMode.PLAN
    assert phase_b.plan_decisions_resolved is True
    assert phase_b.session_id == session_id
    assert phase_b.resume_session_token == "runner-tok-A"


def test_plan_execute_inherits_session_and_resume_token(project_registry, tmp_path):
    conversation_store = SQLiteConversationStore(tmp_path / "exec.sqlite3")
    session_id = conversation_store.resolve_or_create_session("remote-coder", 123, 40, None)
    conversation_store.set_runner_resume_token(session_id, ModelName.CLAUDE.value, "runner-tok-B")

    store = InMemoryJobStore()
    plan_request = JobRequest(
        project="remote-coder",
        model=ModelName.CLAUDE,
        instruction="plan the storage layer",
        mode=JobMode.PLAN,
        chat_id=123,
        requested_by=999,
        message_id=40,
        session_id=session_id,
    )
    plan_job = Job(
        id="job_plan_x",
        request=plan_request,
        status=JobStatus.SUCCEEDED,
        runner_stdout_summary="1. add Store class\n2. wire it",
    )
    store.create(plan_job)

    notifier = DummyNotifier()
    job_manager = CaptureJobManager()
    app, _ = _build_session_app(
        project_registry, notifier, job_manager, conversation_store, store=store
    )
    client = TestClient(app)
    wh = _webhook_url(project_registry)

    resp = _tap_exec(client, wh, 1)
    assert resp.json()["status"] == "accepted"

    agent_request = job_manager.last_request
    assert agent_request is not None
    assert agent_request.mode == JobMode.AGENT
    assert agent_request.session_id == session_id
    assert agent_request.resume_session_token == "runner-tok-B"
