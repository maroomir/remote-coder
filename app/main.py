import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

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
from app.projects.registry import ProjectRegistry, projects_config_path_for_settings
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
    ReportsCommand,
    RebaseCommand,
    StartCommand,
    StatusCommand,
    StopCommand,
)
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

job_store = InMemoryJobStore()
auth_service = AllowlistAuthService(
    set(settings.telegram_allowed_chat_ids), set(settings.telegram_allowed_user_ids)
)
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
        RebaseCommand(),
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

@asynccontextmanager
async def lifespan(_app: FastAPI):
    for chat_id in settings.telegram_allowed_chat_ids:
        try:
            notifier.send_text(chat_id, "✅ Remote AI Coder 서버가 시작되었습니다.")
        except Exception:
            pass
    yield
    for chat_id in settings.telegram_allowed_chat_ids:
        try:
            notifier.send_text(chat_id, "🔴 Remote AI Coder 서버 연결이 종료되었습니다.")
        except Exception:
            pass


app = FastAPI(title="Remote AI Coder", lifespan=lifespan)
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
        auth_service=auth_service,
        parser=parser,
        command_registry=command_registry,
        command_context=command_context,
        job_manager=job_manager,
        job_store=job_store,
        notifier=notifier,
        webhook_secret=(
            settings.telegram_webhook_secret.get_secret_value()
            if settings.telegram_webhook_secret
            else None
        ),
        conversation_store=conversation_store,
    )
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
