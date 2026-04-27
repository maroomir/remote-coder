from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.jobs.store import InMemoryJobStore
from app.models import ModelName
from app.security.auth import AllowlistAuthService
from app.telegram.commands import (
    CommandContext,
    CommandRegistry,
    HelpCommand,
    ModelCommand,
    ProjectsCommand,
    StartCommand,
    StatusCommand,
)
from app.telegram.model_preferences import InMemoryModelPreferenceStore
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


class DummyNotifier:
    def __init__(self):
        self.sent: list[tuple[int, str]] = []

    def send_text(self, chat_id: int, text: str) -> None:
        self.sent.append((chat_id, text))


def test_webhook_accepts_natural_message():
    app = FastAPI()
    store = InMemoryJobStore()
    notifier = DummyNotifier()
    app.include_router(
        create_webhook_router(
            auth_service=AllowlistAuthService({123}),
            parser=CommandParser(default_project="proj", default_model=ModelName.CLAUDE),
            command_registry=CommandRegistry(
                [StartCommand(), HelpCommand(), ModelCommand(), StatusCommand(), ProjectsCommand()]
            ),
            command_context=CommandContext(
                job_store=store,
                default_model=ModelName.CLAUDE,
                projects=["proj"],
                model_preferences=InMemoryModelPreferenceStore(default_model=ModelName.CLAUDE),
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


def test_webhook_sends_command_response_to_telegram():
    app = FastAPI()
    store = InMemoryJobStore()
    notifier = DummyNotifier()
    app.include_router(
        create_webhook_router(
            auth_service=AllowlistAuthService({123}),
            parser=CommandParser(default_project="proj", default_model=ModelName.CLAUDE),
            command_registry=CommandRegistry(
                [StartCommand(), HelpCommand(), ModelCommand(), StatusCommand(), ProjectsCommand()]
            ),
            command_context=CommandContext(
                job_store=store,
                default_model=ModelName.CLAUDE,
                projects=["proj"],
                model_preferences=InMemoryModelPreferenceStore(default_model=ModelName.CLAUDE),
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
