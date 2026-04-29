from fastapi import FastAPI

from app.admin.router import create_admin_router
from app.ai.factory import AiRunnerFactory
from app.config import get_settings
from app.git.branch_naming import TimestampSlugStrategy
from app.git.service import GitWorktreeService
from app.jobs.manager import JobManager
from app.jobs.store import InMemoryJobStore
from app.projects.registry import ProjectRegistry, projects_config_path_for_settings
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

job_store = InMemoryJobStore()
auth_service = AllowlistAuthService(
    set(settings.telegram_allowed_chat_ids), set(settings.telegram_allowed_user_ids)
)
model_preferences = InMemoryModelPreferenceStore(default_model=settings.default_model)
project_preferences = InMemoryProjectPreferenceStore()
conversation_store = SQLiteConversationStore(settings.conversation_db_path)
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
        ProjectsCommand(),
        ProjectCommand(),
        BranchesCommand(),
        BranchCommand(),
        RebaseCommand(),
        ClearCommand(),
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
)

app = FastAPI(title="Remote AI Coder")
app.include_router(create_admin_router(settings, project_registry))
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
