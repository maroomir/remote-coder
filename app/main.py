import asyncio
import logging
import time
from contextlib import asynccontextmanager, suppress
from dataclasses import replace

from fastapi import FastAPI, Request

from app.admin.advanced_settings import AdvancedSettings, FileAdvancedSettingsStore, advanced_settings_path
from app.admin.router import create_admin_router
from app.ai.factory import AiRunnerFactory
from app.config import get_settings, worktrees_root
from app.git.ai_commit import AiCommitBodyGenerator
from app.git.branch_naming import TimestampSlugStrategy
from app.git.service import GitWorktreeService
from app.jobs.manager import JobManager
from app.jobs.store import SQLiteJobStore
from app.monitoring.log_buffer import InMemoryLogBuffer, attach_app_memory_log_handler
from app.monitoring.events import EventLogger
from app.models import ModelName
from app.projects.registry import (
    ProjectRegistry,
    compute_token_hash_prefix,
    projects_config_path,
)
from app.security.auth import AllowlistAuthService
from app.system_startup import run_startup_project_pulls
from app.telegram.commands import (
    CommandContext,
    CommandRegistry,
    TelegramMessage,
    build_default_commands,
)
from app.telegram.bot_instances import BotInstance, BotInstanceManager
from app.telegram.confirmations import InMemoryConfirmationStore
from app.telegram.conversation import SQLiteConversationStore
from app.telegram.notifier import Notifier, TelegramNotifier
from app.telegram.i18n import ui_message
from app.telegram.parser import CommandParser
from app.telegram.model_preferences import InMemoryModelPreferenceStore
from app.telegram.webhook import create_webhook_router
from app.telegram.webhook_registration import TelegramWebhookRegistrar

settings = get_settings()
_projects_path = projects_config_path(settings.projects_config_path)
project_registry = ProjectRegistry(_projects_path)
project_registry.ensure_empty_registry_file()
advanced_settings_store = FileAdvancedSettingsStore(advanced_settings_path())
advanced_settings_store.load()
_adv: AdvancedSettings = advanced_settings_store.get()

log_buffer = InMemoryLogBuffer(max_entries=2000)
attach_app_memory_log_handler(log_buffer)
logging.getLogger("app").info(
    "Remote AI Coder server (re)loaded — log buffer ready"
)
_systemlog = EventLogger("app.system", "system.lifecycle")
_httplog = EventLogger("app.http", "http.request")

job_store = SQLiteJobStore(settings.job_db_path)
model_preferences = InMemoryModelPreferenceStore(default_model=ModelName.CLAUDE)
confirmation_store = InMemoryConfirmationStore()
conversation_store = SQLiteConversationStore(
    settings.conversation_db_path,
    advanced_settings_store=advanced_settings_store,
)
parser = CommandParser(
    project_registry=project_registry,
    default_model=ModelName.CLAUDE,
    model_preferences=model_preferences,
    conversation_store=conversation_store,
    advanced_settings_store=advanced_settings_store,
)
command_registry = CommandRegistry(commands=build_default_commands())
git_service = GitWorktreeService(base_dir=worktrees_root())
command_context = CommandContext(
    job_store=job_store,
    default_model=ModelName.CLAUDE,
    project_registry=project_registry,
    model_preferences=model_preferences,
    project_name=None,
    git_service=git_service,
    git_remote_name=_adv.git_remote_name,
    conversation_store=conversation_store,
    confirmation_store=confirmation_store,
    advanced_settings_store=advanced_settings_store,
)
runner_factory = AiRunnerFactory(advanced_settings_store=advanced_settings_store)
branch_strategy = TimestampSlugStrategy()


def _build_bot_instance(record):
    return BotInstance(
        project_name=record.name,
        token_hash=compute_token_hash_prefix(record.bot_token.get_secret_value()),
        notifier=TelegramNotifier(record.bot_token.get_secret_value(), advanced_settings_store),
        auth_service=AllowlistAuthService(set(record.allowed_chat_ids), set(record.allowed_user_ids)),
        command_context=command_context,
        webhook_secret=record.webhook_secret.get_secret_value() if record.webhook_secret else None,
    )


bot_instance_manager = BotInstanceManager(_build_bot_instance)
for project in project_registry.list_projects():
    if project.enabled:
        bot_instance_manager.register(project)


def _notifier_for_project(project_name: str) -> Notifier:
    instance = bot_instance_manager.get_by_name(project_name)
    if instance is None:
        raise RuntimeError(
            "No Telegram notifier bot instance found for project. "
            f"project={project_name!r}"
        )
    return instance.notifier


job_manager = JobManager(
    settings=settings,
    job_store=job_store,
    git_service=git_service,
    runner_factory=runner_factory,
    branch_strategy=branch_strategy,
    notifier_resolver=_notifier_for_project,
    project_registry=project_registry,
    advanced_settings_store=advanced_settings_store,
    ai_commit_body_generator=AiCommitBodyGenerator(),
)
command_context.job_manager = job_manager
webhook_registrar = (
    TelegramWebhookRegistrar(
        settings.telegram_webhook_public_base_url,
        bot_commands=command_registry.bot_commands(advanced_settings_store.get().ui_language),
    )
    if settings.telegram_webhook_public_base_url
    else None
)


def _run_startup_side_effects(instances: list[BotInstance], adv: AdvancedSettings) -> None:
    startup_chat_total = sum(len(inst.auth_service.allowed_chat_ids) for inst in instances)
    _systemlog.info(
        "lifespan startup notifying allowed chats count=%d projects=%d default_model=%s",
        startup_chat_total,
        len(project_registry.list_projects()),
        ModelName.CLAUDE.value,
    )
    run_startup_project_pulls(
        pull_projects_on_server_startup_enabled=adv.pull_projects_on_server_startup_enabled,
        project_registry=project_registry,
        git_service=git_service,
        remote=adv.git_remote_name,
        system_log=_systemlog,
    )
    for instance in instances:
        ctx = replace(instance.command_context, project_name=instance.project_name)
        bot_notifier = instance.notifier
        for chat_id in instance.auth_service.allowed_chat_ids:
            try:
                response = command_registry.dispatch_rich(
                    TelegramMessage(chat_id=chat_id, user_id=None, text="/start"),
                    ctx,
                )
                if response:
                    text = ui_message(
                        "server.started",
                        "✅ Remote AI Coder server started.\n{body}",
                        body=response.text,
                    )
                    if response.inline_buttons:
                        bot_notifier.send_with_buttons(chat_id, text, response.inline_buttons)
                    else:
                        bot_notifier.send_text(chat_id, text)
                    _systemlog.info("startup notification sent", chat_id=chat_id)
            except Exception:
                _systemlog.exception("startup notification failed", chat_id=chat_id)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    instances = bot_instance_manager.list_all()
    startup_task = asyncio.create_task(
        asyncio.to_thread(
            _run_startup_side_effects,
            instances,
            advanced_settings_store.get(),
        )
    )
    yield
    if not startup_task.done():
        startup_task.cancel()
    with suppress(asyncio.CancelledError):
        await startup_task
    shutdown_instances = bot_instance_manager.list_all()
    shutdown_chat_total = sum(len(inst.auth_service.allowed_chat_ids) for inst in shutdown_instances)
    _systemlog.info("lifespan shutdown notifying allowed chats count=%d", shutdown_chat_total)
    for instance in shutdown_instances:
        bot_notifier = instance.notifier
        for chat_id in instance.auth_service.allowed_chat_ids:
            try:
                bot_notifier.send_text(
                    chat_id,
                    ui_message(
                        "server.shutdown",
                        "🔴 Remote AI Coder server connection closed.",
                    ),
                )
                _systemlog.info("shutdown notification sent", chat_id=chat_id)
            except Exception:
                _systemlog.exception("shutdown notification failed", chat_id=chat_id)


app = FastAPI(title="Remote AI Coder", lifespan=lifespan)


@app.middleware("http")
async def log_http_request(request: Request, call_next):
    start = time.perf_counter()
    path = request.url.path
    method = request.method
    client_host = request.client.host if request.client else "-"
    _httplog.info("request start method=%s path=%s client=%s", method, path, client_host)
    try:
        response = await call_next(request)
    except Exception:
        dur_ms = int((time.perf_counter() - start) * 1000)
        _httplog.exception(
            "request failed method=%s path=%s client=%s dur_ms=%d",
            method,
            path,
            client_host,
            dur_ms,
        )
        raise
    dur_ms = int((time.perf_counter() - start) * 1000)
    _httplog.info(
        "request done method=%s path=%s status=%d dur_ms=%d client=%s",
        method,
        path,
        response.status_code,
        dur_ms,
        client_host,
    )
    return response
app.include_router(
    create_admin_router(
        settings,
        project_registry,
        advanced_settings_store,
        log_buffer,
        conversation_store,
        bot_instance_manager=bot_instance_manager,
        webhook_registrar=webhook_registrar,
        bot_commands_builder=command_registry.bot_commands,
    )
)
app.include_router(
    create_webhook_router(
        bot_instance_manager=bot_instance_manager,
        parser=parser,
        command_registry=command_registry,
        job_manager=job_manager,
        job_store=job_store,
        conversation_store=conversation_store,
    )
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
