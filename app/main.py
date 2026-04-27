from fastapi import FastAPI

from app.ai.factory import AiRunnerFactory
from app.config import get_settings
from app.git.branch_naming import TimestampSlugStrategy
from app.git.service import GitWorktreeService
from app.jobs.manager import JobManager
from app.jobs.store import InMemoryJobStore
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
from app.telegram.notifier import TelegramNotifier
from app.telegram.parser import CommandParser
from app.telegram.webhook import create_webhook_router

settings = get_settings()
job_store = InMemoryJobStore()
auth_service = AllowlistAuthService(set(settings.telegram_allowed_chat_ids))
parser = CommandParser(default_project=settings.default_project, default_model=settings.default_model)
command_registry = CommandRegistry(
    commands=[StartCommand(), HelpCommand(), ModelCommand(), StatusCommand(), ProjectsCommand()]
)
command_context = CommandContext(
    job_store=job_store,
    default_model=settings.default_model,
    projects=[settings.default_project],
)
git_service = GitWorktreeService(base_dir=settings.worktree_base_dir)
runner_factory = AiRunnerFactory()
branch_strategy = TimestampSlugStrategy()
notifier = TelegramNotifier(settings.telegram_bot_token.get_secret_value())
job_manager = JobManager(
    settings=settings,
    job_store=job_store,
    git_service=git_service,
    runner_factory=runner_factory,
    branch_strategy=branch_strategy,
    notifier=notifier,
)

app = FastAPI(title="Remote AI Coder")
app.include_router(
    create_webhook_router(
        auth_service=auth_service,
        parser=parser,
        command_registry=command_registry,
        command_context=command_context,
        job_manager=job_manager,
        job_store=job_store,
        webhook_secret=(
            settings.telegram_webhook_secret.get_secret_value()
            if settings.telegram_webhook_secret
            else None
        ),
    )
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
