from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.jobs.store import InMemoryJobStore
from app.models import ModelName
from app.security.auth import AllowlistAuthService
from app.telegram.commands import (
    BranchCommand,
    BranchesCommand,
    ClearCommand,
    CommandContext,
    CommandRegistry,
    HelpCommand,
    ModelCommand,
    ProjectCommand,
    ProjectsCommand,
    RebaseCommand,
    StartCommand,
    StatusCommand,
)
from app.telegram.confirmations import InMemoryConfirmationStore
from app.telegram.conversation import SQLiteConversationStore
from app.telegram.model_preferences import InMemoryModelPreferenceStore
from app.telegram.project_preferences import InMemoryProjectPreferenceStore
from app.telegram.parser import CommandParser
from app.telegram.webhook import create_webhook_router


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


class DummyNotifier:
    def __init__(self):
        self.sent: list[tuple[int, str]] = []

    def send_text(self, chat_id: int, text: str) -> None:
        self.sent.append((chat_id, text))


def test_webhook_accepts_natural_message(project_registry):
    app = FastAPI()
    store = InMemoryJobStore()
    notifier = DummyNotifier()
    app.include_router(
        create_webhook_router(
            auth_service=AllowlistAuthService({123}),
            parser=CommandParser(
                project_registry=project_registry,
                default_model=ModelName.CLAUDE,
            ),
            command_registry=CommandRegistry(
                [
                    StartCommand(),
                    HelpCommand(),
                    ModelCommand(),
                    StatusCommand(),
                    ProjectsCommand(),
                    ProjectCommand(),
                    BranchesCommand(),
                    BranchCommand(),
                    RebaseCommand(),
                    ClearCommand(),
                ]
            ),
            command_context=CommandContext(
                job_store=store,
                default_model=ModelName.CLAUDE,
                project_registry=project_registry,
                model_preferences=InMemoryModelPreferenceStore(default_model=ModelName.CLAUDE),
                project_preferences=InMemoryProjectPreferenceStore(),
                git_service=Mock(),
                git_remote_name="origin",
                conversation_store=None,
                confirmation_store=InMemoryConfirmationStore(),
            ),
            job_manager=DummyJobManager(),
            job_store=store,
            notifier=notifier,
            webhook_secret=None,
        )
    )
    client = TestClient(app)
    payload = {
        "update_id": 1,
        "message": {"message_id": 1, "text": "fix tests", "chat": {"id": 123}, "from": {"id": 999}},
    }
    response = client.post("/telegram/webhook", json=payload)
    assert response.status_code == 200
    assert response.json()["status"] == "accepted"


def test_webhook_sends_command_response_to_telegram(project_registry):
    app = FastAPI()
    store = InMemoryJobStore()
    notifier = DummyNotifier()
    app.include_router(
        create_webhook_router(
            auth_service=AllowlistAuthService({123}),
            parser=CommandParser(
                project_registry=project_registry,
                default_model=ModelName.CLAUDE,
            ),
            command_registry=CommandRegistry(
                [
                    StartCommand(),
                    HelpCommand(),
                    ModelCommand(),
                    StatusCommand(),
                    ProjectsCommand(),
                    ProjectCommand(),
                    BranchesCommand(),
                    BranchCommand(),
                    RebaseCommand(),
                    ClearCommand(),
                ]
            ),
            command_context=CommandContext(
                job_store=store,
                default_model=ModelName.CLAUDE,
                project_registry=project_registry,
                model_preferences=InMemoryModelPreferenceStore(default_model=ModelName.CLAUDE),
                project_preferences=InMemoryProjectPreferenceStore(),
                git_service=Mock(),
                git_remote_name="origin",
                conversation_store=None,
                confirmation_store=InMemoryConfirmationStore(),
            ),
            job_manager=DummyJobManager(),
            job_store=store,
            notifier=notifier,
            webhook_secret=None,
        )
    )
    client = TestClient(app)
    payload = {
        "update_id": 1,
        "message": {"message_id": 1, "text": "/help", "chat": {"id": 123}, "from": {"id": 999}},
    }
    response = client.post("/telegram/webhook", json=payload)

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert notifier.sent
    assert notifier.sent[0][0] == 123


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
        project_preferences=InMemoryProjectPreferenceStore(),
        git_service=git_service,
        git_remote_name="origin",
        conversation_store=None,
        confirmation_store=InMemoryConfirmationStore(),
    )
    app.include_router(
        create_webhook_router(
            auth_service=AllowlistAuthService({123}),
            parser=CommandParser(
                project_registry=project_registry,
                default_model=ModelName.CLAUDE,
            ),
            command_registry=CommandRegistry(
                [
                    StartCommand(),
                    HelpCommand(),
                    ModelCommand(),
                    StatusCommand(),
                    ProjectsCommand(),
                    ProjectCommand(),
                    BranchesCommand(),
                    BranchCommand(),
                    RebaseCommand(),
                    ClearCommand(),
                ]
            ),
            command_context=command_context,
            job_manager=DummyJobManager(),
            job_store=store,
            notifier=notifier,
            webhook_secret=None,
        )
    )
    client = TestClient(app)

    prompt_response = client.post(
        "/telegram/webhook",
        json={
            "update_id": 10,
            "message": {"message_id": 10, "text": "/clear branch", "chat": {"id": 123}, "from": {"id": 999}},
        },
    )
    confirm_response = client.post(
        "/telegram/webhook",
        json={
            "update_id": 11,
            "message": {"message_id": 11, "text": "Y", "chat": {"id": 123}, "from": {"id": 999}},
        },
    )

    assert prompt_response.status_code == 200
    assert prompt_response.json()["status"] == "ok"
    assert confirm_response.status_code == 200
    assert confirm_response.json()["status"] == "ok"
    assert "현재 할 작업" in notifier.sent[0][1]
    assert "원격 1개" in notifier.sent[1][1]


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
    app.include_router(
        create_webhook_router(
            auth_service=AllowlistAuthService({123}),
            parser=parser,
            command_registry=CommandRegistry(
                [
                    StartCommand(),
                    HelpCommand(),
                    ModelCommand(),
                    StatusCommand(),
                    ProjectsCommand(),
                    ProjectCommand(),
                    BranchesCommand(),
                    BranchCommand(),
                    RebaseCommand(),
                    ClearCommand(),
                ]
            ),
            command_context=CommandContext(
                job_store=store,
                default_model=ModelName.CLAUDE,
                project_registry=project_registry,
                model_preferences=InMemoryModelPreferenceStore(default_model=ModelName.CLAUDE),
                project_preferences=InMemoryProjectPreferenceStore(),
                git_service=Mock(),
                git_remote_name="origin",
                conversation_store=conv,
                confirmation_store=InMemoryConfirmationStore(),
            ),
            job_manager=capture,
            job_store=store,
            notifier=notifier,
            webhook_secret=None,
            conversation_store=conv,
        )
    )
    client = TestClient(app)
    response = client.post(
        "/telegram/webhook",
        json={
            "update_id": 2,
            "message": {"message_id": 2, "text": "작업 시작해줘", "chat": {"id": 123}, "from": {"id": 999}},
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "accepted"
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
    app.include_router(
        create_webhook_router(
            auth_service=AllowlistAuthService({123}),
            parser=parser,
            command_registry=CommandRegistry(
                [
                    StartCommand(),
                    HelpCommand(),
                    ModelCommand(),
                    StatusCommand(),
                    ProjectsCommand(),
                    ProjectCommand(),
                    BranchesCommand(),
                    BranchCommand(),
                    RebaseCommand(),
                    ClearCommand(),
                ]
            ),
            command_context=CommandContext(
                job_store=store,
                default_model=ModelName.CLAUDE,
                project_registry=project_registry,
                model_preferences=InMemoryModelPreferenceStore(default_model=ModelName.CLAUDE),
                project_preferences=InMemoryProjectPreferenceStore(),
                git_service=Mock(),
                git_remote_name="origin",
                conversation_store=conv,
                confirmation_store=InMemoryConfirmationStore(),
            ),
            job_manager=DummyJobManager(),
            job_store=store,
            notifier=notifier,
            webhook_secret=None,
            conversation_store=conv,
        )
    )
    client = TestClient(app)
    response = client.post(
        "/telegram/webhook",
        json={
            "update_id": 3,
            "message": {"message_id": 3, "text": "진행해줘", "chat": {"id": 123}, "from": {"id": 999}},
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"
    assert notifier.sent
    assert "맥락" in notifier.sent[0][1]


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
    app.include_router(
        create_webhook_router(
            auth_service=AllowlistAuthService({123, 999}),
            parser=parser,
            command_registry=CommandRegistry(
                [
                    StartCommand(),
                    HelpCommand(),
                    ModelCommand(),
                    StatusCommand(),
                    ProjectsCommand(),
                    ProjectCommand(),
                    BranchesCommand(),
                    BranchCommand(),
                    RebaseCommand(),
                    ClearCommand(),
                ]
            ),
            command_context=CommandContext(
                job_store=store,
                default_model=ModelName.CLAUDE,
                project_registry=project_registry,
                model_preferences=InMemoryModelPreferenceStore(default_model=ModelName.CLAUDE),
                project_preferences=InMemoryProjectPreferenceStore(),
                git_service=Mock(),
                git_remote_name="origin",
                conversation_store=conv,
                confirmation_store=InMemoryConfirmationStore(),
            ),
            job_manager=capture,
            job_store=store,
            notifier=notifier,
            webhook_secret=None,
            conversation_store=conv,
        )
    )
    client = TestClient(app)
    response = client.post(
        "/telegram/webhook",
        json={
            "update_id": 4,
            "message": {"message_id": 4, "text": "작업 시작해줘", "chat": {"id": 123}, "from": {"id": 1}},
        },
    )
    assert response.json()["status"] == "ignored"
    assert "맥락" in notifier.sent[-1][1]
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
    app.include_router(
        create_webhook_router(
            auth_service=AllowlistAuthService({123}),
            parser=parser,
            command_registry=CommandRegistry(
                [
                    StartCommand(),
                    HelpCommand(),
                    ModelCommand(),
                    StatusCommand(),
                    ProjectsCommand(),
                    ProjectCommand(),
                    BranchesCommand(),
                    BranchCommand(),
                    RebaseCommand(),
                    ClearCommand(),
                ]
            ),
            command_context=CommandContext(
                job_store=store,
                default_model=ModelName.CLAUDE,
                project_registry=project_registry,
                model_preferences=InMemoryModelPreferenceStore(default_model=ModelName.CLAUDE),
                project_preferences=InMemoryProjectPreferenceStore(),
                git_service=Mock(),
                git_remote_name="origin",
                conversation_store=conv,
                confirmation_store=InMemoryConfirmationStore(),
            ),
            job_manager=capture,
            job_store=store,
            notifier=notifier,
            webhook_secret=None,
            conversation_store=conv,
        )
    )
    client = TestClient(app)
    response = client.post(
        "/telegram/webhook",
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

    assert response.status_code == 200
    assert response.json()["status"] == "accepted"
    assert capture.last_request is not None
    assert capture.last_request.branch == "remote-a"
    assert capture.last_request.reply_to_message_id == 1
    assert conv.get_bound_branch("remote-coder", 123, 2) == "remote-a"
