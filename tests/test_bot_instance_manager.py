from pathlib import Path
from unittest.mock import Mock

from pydantic import SecretStr

from app.jobs.store import InMemoryJobStore
from app.models import ModelName
from app.projects.registry import ProjectRecord, compute_token_hash_prefix
from app.security.auth import AllowlistAuthService
from app.telegram.bot_instances import BotInstance, BotInstanceManager
from app.telegram.commands import CommandContext
from app.telegram.confirmations import InMemoryConfirmationStore
from app.telegram.model_preferences import InMemoryModelPreferenceStore


def _record(tmp_path: Path, name: str, token: str) -> ProjectRecord:
    root = tmp_path / name / "repo"
    root.mkdir(parents=True, exist_ok=True)
    wt = tmp_path / name / "wt"
    wt.mkdir(parents=True, exist_ok=True)
    return ProjectRecord(
        name=name,
        root_path=root,
        worktree_base_dir=wt,
        default_model=ModelName.CLAUDE,
        enabled=True,
        bot_token=SecretStr(token),
        allowed_chat_ids=[1],
    )


def _dummy_factory():
    def factory(r: ProjectRecord) -> BotInstance:
        store = InMemoryJobStore()
        ctx = CommandContext(
            job_store=store,
            default_model=ModelName.CLAUDE,
            project_registry=Mock(),
            model_preferences=InMemoryModelPreferenceStore(default_model=ModelName.CLAUDE),
            project_name=r.name,
            git_service=Mock(),
            git_remote_name="origin",
            conversation_store=None,
            confirmation_store=InMemoryConfirmationStore(),
        )
        return BotInstance(
            project_name=r.name,
            token_hash=compute_token_hash_prefix(r.bot_token.get_secret_value()),
            notifier=Mock(),
            auth_service=AllowlistAuthService(set(r.allowed_chat_ids)),
            command_context=ctx,
            webhook_secret=r.webhook_secret.get_secret_value() if r.webhook_secret else None,
        )

    return factory


def test_bot_instance_manager_register_and_get_prefix_key(tmp_path: Path) -> None:
    mgr = BotInstanceManager(_dummy_factory())
    rec = _record(tmp_path, "p1", "token-one")
    mgr.register(rec)
    key = compute_token_hash_prefix("token-one")
    got = mgr.get(key)
    assert got is not None
    assert got.project_name == "p1"
    assert got.token_hash == key


def test_bot_instance_manager_get_wrong_length_returns_none(tmp_path: Path) -> None:
    mgr = BotInstanceManager(_dummy_factory())
    rec = _record(tmp_path, "p1", "token-prefix-test")
    mgr.register(rec)
    key = compute_token_hash_prefix("token-prefix-test")
    assert len(key) == 16
    got = mgr.get(key)
    assert got is not None
    assert got.project_name == "p1"
    assert mgr.get(key[:15]) is None


def test_bot_instance_manager_register_same_name_replaces_hash(tmp_path: Path) -> None:
    mgr = BotInstanceManager(_dummy_factory())
    mgr.register(_record(tmp_path, "same", "old-token"))
    old_key = compute_token_hash_prefix("old-token")
    mgr.register(_record(tmp_path, "same", "new-token"))
    assert mgr.get(old_key) is None
    assert mgr.get(compute_token_hash_prefix("new-token")) is not None
    assert mgr.get_by_name("same") is not None
    assert mgr.get_by_name("same").token_hash == compute_token_hash_prefix("new-token")


def test_bot_instance_manager_unregister(tmp_path: Path) -> None:
    mgr = BotInstanceManager(_dummy_factory())
    rec = _record(tmp_path, "gone", "tok")
    mgr.register(rec)
    assert mgr.unregister("gone") is True
    assert mgr.unregister("gone") is False
    assert mgr.get(compute_token_hash_prefix("tok")) is None
    assert mgr.get_by_name("gone") is None


def test_bot_instance_manager_get_empty_returns_none(tmp_path: Path) -> None:
    mgr = BotInstanceManager(_dummy_factory())
    mgr.register(_record(tmp_path, "x", "t"))
    assert mgr.get("") is None


def test_bot_instance_manager_list_all(tmp_path: Path) -> None:
    mgr = BotInstanceManager(_dummy_factory())
    mgr.register(_record(tmp_path, "a", "ta"))
    mgr.register(_record(tmp_path, "b", "tb"))
    names = {i.project_name for i in mgr.list_all()}
    assert names == {"a", "b"}
