"""Webhook routing and notifier isolation across multiple bot instances."""

from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.jobs.store import InMemoryJobStore
from app.models import ModelName
from app.projects.registry import ProjectRecord, compute_token_hash_prefix
from app.security.auth import AllowlistAuthService
from app.telegram.bot_instances import BotInstance, BotInstanceManager
from app.telegram.commands import CommandContext, CommandRegistry, HelpCommand, ModelCommand, StartCommand
from app.telegram.confirmations import InMemoryConfirmationStore
from app.telegram.model_preferences import InMemoryModelPreferenceStore
from app.telegram.parser import CommandParser
from app.telegram.webhook import create_webhook_router


class DummyNotifier:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []

    def send_text(self, chat_id: int, text: str, **kwargs) -> None:
        self.sent.append((chat_id, text))

    def send_with_buttons(self, chat_id: int, text: str, inline_buttons, **kwargs) -> None:
        self.sent.append((chat_id, text))

    def answer_callback_query(self, callback_query_id: str) -> None:
        _ = callback_query_id


class DummyJob:
    id = "job_multibot_1"


class DummyJobManager:
    def submit(self, request):
        _ = request
        return DummyJob()

    def run(self, job_id: str):
        _ = job_id
        return None


def _make_app_two_projects(project_registry, *, job_store, notifiers_by_project: dict[str, DummyNotifier]):
    git_service = Mock()
    git_service.get_current_branch.return_value = "main"

    def factory(r: ProjectRecord) -> BotInstance:
        n = DummyNotifier()
        notifiers_by_project[r.name] = n
        ctx = CommandContext(
            job_store=job_store,
            default_model=ModelName.CLAUDE,
            project_registry=project_registry,
            model_preferences=InMemoryModelPreferenceStore(default_model=ModelName.CLAUDE),
            project_name=None,
            git_service=git_service,
            git_remote_name="origin",
            conversation_store=None,
            confirmation_store=InMemoryConfirmationStore(),
        )
        return BotInstance(
            project_name=r.name,
            token_hash=compute_token_hash_prefix(r.bot_token.get_secret_value()),
            notifier=n,
            auth_service=AllowlistAuthService(set(r.allowed_chat_ids)),
            command_context=ctx,
            webhook_secret=r.webhook_secret.get_secret_value() if r.webhook_secret else None,
        )

    mgr = BotInstanceManager(factory)
    for rec in project_registry.list_projects():
        mgr.register(rec)

    app = FastAPI()
    app.include_router(
        create_webhook_router(
            bot_instance_manager=mgr,
            parser=CommandParser(
                project_registry=project_registry,
                default_model=ModelName.CLAUDE,
            ),
            command_registry=CommandRegistry([StartCommand(), HelpCommand(), ModelCommand()]),
            job_manager=DummyJobManager(),
            job_store=job_store,
            conversation_store=None,
        )
    )
    return app


def test_natural_message_routes_to_bound_project_and_notifier(project_registry, tmp_path):
    root_b = tmp_path / "svc_b_repo"
    root_b.mkdir()
    wt_b = tmp_path / "svc_b_wt"
    wt_b.mkdir()
    project_registry.add_project(
        ProjectRecord(
            name="svc-b",
            root_path=root_b,
            worktree_base_dir=wt_b,
            default_model=ModelName.CLAUDE,
            enabled=True,
            bot_token="777:svc-b-bot-token-unique",
            allowed_chat_ids=[123],
        )
    )

    job_store = InMemoryJobStore()
    notifiers: dict[str, DummyNotifier] = {}
    app = _make_app_two_projects(project_registry, job_store=job_store, notifiers_by_project=notifiers)
    client = TestClient(app)

    rec_a = project_registry.get("remote-coder")
    rec_b = project_registry.get("svc-b")
    assert rec_a is not None and rec_b is not None
    url_a = f"/telegram/webhook/{compute_token_hash_prefix(rec_a.bot_token.get_secret_value())}"
    url_b = f"/telegram/webhook/{compute_token_hash_prefix(rec_b.bot_token.get_secret_value())}"

    payload = {
        "update_id": 1,
        "message": {"message_id": 1, "text": "fix typos", "chat": {"id": 123}, "from": {"id": 999}},
    }

    r_a = client.post(url_a, json=payload)
    r_b = client.post(url_b, json=payload)
    assert r_a.status_code == 200
    assert r_b.status_code == 200

    assert notifiers["remote-coder"].sent
    assert notifiers["svc-b"].sent
    assert "- 프로젝트: remote-coder" in notifiers["remote-coder"].sent[0][1]
    assert "- 프로젝트: svc-b" in notifiers["svc-b"].sent[0][1]


def test_webhook_posts_do_not_cross_notify_between_bots(project_registry, tmp_path):
    root_b = tmp_path / "svc_b2_repo"
    root_b.mkdir()
    wt_b = tmp_path / "svc_b2_wt"
    wt_b.mkdir()
    project_registry.add_project(
        ProjectRecord(
            name="svc-b2",
            root_path=root_b,
            worktree_base_dir=wt_b,
            default_model=ModelName.CLAUDE,
            enabled=True,
            bot_token="888:svc-b2-bot-token",
            allowed_chat_ids=[123],
        )
    )

    job_store = InMemoryJobStore()
    notifiers: dict[str, DummyNotifier] = {}
    app = _make_app_two_projects(project_registry, job_store=job_store, notifiers_by_project=notifiers)
    client = TestClient(app)

    rec_b = project_registry.get("svc-b2")
    assert rec_b is not None
    url_b = f"/telegram/webhook/{compute_token_hash_prefix(rec_b.bot_token.get_secret_value())}"
    payload = {
        "update_id": 10,
        "message": {"message_id": 10, "text": "hello", "chat": {"id": 123}, "from": {"id": 999}},
    }

    client.post(url_b, json=payload)

    assert notifiers["svc-b2"].sent
    assert not notifiers["remote-coder"].sent


def test_webhook_invalid_hash_length_returns_404(project_registry):
    job_store = InMemoryJobStore()
    notifiers: dict[str, DummyNotifier] = {}
    app = _make_app_two_projects(project_registry, job_store=job_store, notifiers_by_project=notifiers)
    client = TestClient(app)

    assert client.post("/telegram/webhook/" + "a" * 15, json={"update_id": 1}).status_code == 404
    assert client.post("/telegram/webhook/" + "g" * 16, json={"update_id": 1}).status_code == 404


def test_webhook_unknown_prefix_returns_404(project_registry):
    job_store = InMemoryJobStore()
    notifiers: dict[str, DummyNotifier] = {}
    app = _make_app_two_projects(project_registry, job_store=job_store, notifiers_by_project=notifiers)
    client = TestClient(app)

    orphan = compute_token_hash_prefix("token-that-is-not-in-registry-" + "x" * 40)
    rec = project_registry.get("remote-coder")
    assert rec is not None
    assert orphan != compute_token_hash_prefix(rec.bot_token.get_secret_value())

    assert client.post(f"/telegram/webhook/{orphan}", json={"update_id": 1}).status_code == 404
