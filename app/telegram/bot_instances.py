from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock

from app.projects.registry import ProjectRecord
from app.security.auth import AllowlistAuthService
from app.telegram.commands import CommandContext
from app.telegram.notifier import TelegramNotifier


@dataclass(frozen=True)
class BotInstance:
    project_name: str
    token_hash: str
    notifier: TelegramNotifier
    auth_service: AllowlistAuthService
    command_context: CommandContext
    webhook_secret: str | None = None


BotInstanceFactory = Callable[[ProjectRecord], BotInstance]


class BotInstanceManager:
    # NOTE: 공유 싱글턴(JobManager, GitWorktreeService, parser, command_registry, conversation_store 등)은
    # factory 클로저에서 캡쳐해 BotInstance 의 command_context 로 주입한다. 본 매니저는 봇별로 분리되는
    # notifier / auth_service / command_context 만 보관·라우팅한다.

    def __init__(self, factory: BotInstanceFactory) -> None:
        self._factory = factory
        self._lock = Lock()
        self._by_name: dict[str, BotInstance] = {}
        self._by_hash: dict[str, BotInstance] = {}

    def register(self, record: ProjectRecord) -> BotInstance:
        instance = self._factory(record)
        with self._lock:
            previous = self._by_name.get(instance.project_name)
            if previous is not None:
                self._by_hash.pop(previous.token_hash, None)
            self._by_name[instance.project_name] = instance
            self._by_hash[instance.token_hash] = instance
        return instance

    def unregister(self, name: str) -> bool:
        with self._lock:
            removed = self._by_name.pop(name, None)
            if removed is None:
                return False
            self._by_hash.pop(removed.token_hash, None)
            return True

    def get(self, token_hash: str) -> BotInstance | None:
        if not token_hash:
            return None
        with self._lock:
            return self._by_hash.get(token_hash)

    def get_by_name(self, name: str) -> BotInstance | None:
        with self._lock:
            return self._by_name.get(name)

    def list_all(self) -> list[BotInstance]:
        with self._lock:
            return list(self._by_name.values())
