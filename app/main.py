import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from app.admin.advanced_settings import FileAdvancedSettingsStore, advanced_settings_path_for_project_root
from app.admin.router import create_admin_router
from app.ai.factory import AiRunnerFactory
from app.config import get_settings
from app.git.ai_commit import AiCommitBodyGenerator
from app.git.branch_naming import TimestampSlugStrategy
from app.git.service import GitWorktreeService
from app.jobs.manager import JobManager
from app.jobs.store import InMemoryJobStore
from app.monitoring.log_buffer import InMemoryLogBuffer, attach_app_memory_log_handler
from app.monitoring.events import EventLogger
from app.projects.registry import ProjectRegistry, compute_token_hash, projects_config_path_for_settings
from app.security.auth import AllowlistAuthService
from app.telegram.commands import (
    BranchCommand,
    ClearCommand,
    CommandContext,
    CommandRegistry,
    HelpCommand,
    InitCommand,
    ModelCommand,
    MonitorCommand,
    ProjectCommand,
    PrCommand,
    PullCommand,
    ReportsCommand,
    RebaseCommand,
    StartCommand,
    StatusCommand,
    StopCommand,
    TelegramMessage,
)
from app.telegram.bot_instances import BotInstance, BotInstanceManager
from app.telegram.confirmations import InMemoryConfirmationStore
from app.telegram.conversation import SQLiteConversationStore
from app.telegram.notifier import TelegramNotifier
from app.telegram.parser import CommandParser
from app.telegram.model_preferences import InMemoryModelPreferenceStore
from app.telegram.project_preferences import InMemoryProjectPreferenceStore
from app.telegram.webhook import create_webhook_router

settings = get_settings()
_projects_path = projects_config_path_for_settings(settings.project_root, settings.projects_config_path)
project_registry = ProjectRegistry(_projects_path)
project_registry.ensure_seeded_from_settings(settings)
_advanced_settings_path = advanced_settings_path_for_project_root(settings.project_root)
advanced_settings_store = FileAdvancedSettingsStore(_advanced_settings_path)
advanced_settings_store.load()

log_buffer = InMemoryLogBuffer(max_entries=2000)
attach_app_memory_log_handler(log_buffer)
logging.getLogger("app").info(
    "Remote AI Coder server (re)loaded — log buffer ready"
)
_systemlog = EventLogger("app.system", "system.lifecycle")
_httplog = EventLogger("app.http", "http.request")

job_store = InMemoryJobStore()
model_preferences = InMemoryModelPreferenceStore(default_model=settings.default_model)
project_preferences = InMemoryProjectPreferenceStore()
confirmation_store = InMemoryConfirmationStore()
conversation_store = SQLiteConversationStore(
    settings.conversation_db_path,
    advanced_settings_store=advanced_settings_store,
)
parser = CommandParser(
    project_registry=project_registry,
    default_model=settings.default_model,
    model_preferences=model_preferences,
    project_preferences=project_preferences,
    conversation_store=conversation_store,
    conversation_recent_limit=settings.conversation_recent_limit,
)
command_registry = CommandRegistry(
    commands=[
        StartCommand(),
        HelpCommand(),
        ModelCommand(),
        StatusCommand(),
        ProjectCommand(),
        InitCommand(),
        ReportsCommand(),
        BranchCommand(),
        PullCommand(),
        RebaseCommand(),
        PrCommand(),
        MonitorCommand(),
        ClearCommand(),
        StopCommand(),
    ]
)
git_service = GitWorktreeService(base_dir=settings.worktree_base_dir)
command_context = CommandContext(
    job_store=job_store,
    default_model=settings.default_model,
    project_registry=project_registry,
    model_preferences=model_preferences,
    project_preferences=project_preferences,
    git_service=git_service,
    git_remote_name=settings.git_remote_name,
    conversation_store=conversation_store,
    confirmation_store=confirmation_store,
    advanced_settings_store=advanced_settings_store,
)
runner_factory = AiRunnerFactory(codex_sandbox=settings.codex_sandbox)
branch_strategy = TimestampSlugStrategy()
notifier = TelegramNotifier(settings.telegram_bot_token.get_secret_value())
job_manager = JobManager(
    settings=settings,
    job_store=job_store,
    git_service=git_service,
    runner_factory=runner_factory,
    branch_strategy=branch_strategy,
    notifier=notifier,
    project_registry=project_registry,
    advanced_settings_store=advanced_settings_store,
    ai_commit_body_generator=AiCommitBodyGenerator(),
)
command_context.job_manager = job_manager
def _build_bot_instance(record):
    return BotInstance(
        project_name=record.name,
        token_hash=compute_token_hash(record.bot_token.get_secret_value()),
        notifier=TelegramNotifier(record.bot_token.get_secret_value()),
        auth_service=AllowlistAuthService(set(record.allowed_chat_ids), set(record.allowed_user_ids)),
        command_context=command_context,
        webhook_secret=record.webhook_secret.get_secret_value() if record.webhook_secret else None,
    )


bot_instance_manager = BotInstanceManager(_build_bot_instance)
for project in project_registry.list_projects():
    if project.enabled:
        bot_instance_manager.register(project)

@asynccontextmanager
async def lifespan(_app: FastAPI):
    _systemlog.info(
        "lifespan startup notifying allowed chats count=%d projects=%d default_model=%s",
        len(settings.telegram_allowed_chat_ids),
        len(project_registry.list_projects()),
        settings.default_model.value,
    )
    for chat_id in settings.telegram_allowed_chat_ids:
        try:
            response = command_registry.dispatch_rich(
                TelegramMessage(chat_id=chat_id, user_id=None, text="/start"),
                command_context,
            )
            if response:
                text = f"✅ Remote AI Coder 서버가 시작되었습니다.\n{response.text}"
                if response.inline_buttons:
                    notifier.send_with_buttons(chat_id, text, response.inline_buttons)
                else:
                    notifier.send_text(chat_id, text)
                _systemlog.info("startup notification sent", chat_id=chat_id)
        except Exception:
            _systemlog.exception("startup notification failed", chat_id=chat_id)
    yield
    _systemlog.info("lifespan shutdown notifying allowed chats count=%d", len(settings.telegram_allowed_chat_ids))
    for chat_id in settings.telegram_allowed_chat_ids:
        try:
            notifier.send_text(chat_id, "🔴 Remote AI Coder 서버 연결이 종료되었습니다.")
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
