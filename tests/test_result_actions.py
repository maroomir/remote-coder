from unittest.mock import Mock

from app.jobs.schemas import Job, JobRequest, JobStatus
from app.jobs.store import InMemoryJobStore
from app.models import ModelName
from app.projects.registry import ProjectRegistry
from app.telegram.commands import CommandContext, CommandRegistry, InlineButton, TelegramMessage
from app.telegram.commands.result_actions import CherryPickCommand, DiscardCommand
from app.telegram.confirmations import InMemoryConfirmationStore
from app.telegram.model_preferences import InMemoryModelPreferenceStore


def _ctx_with_branch(project_registry: ProjectRegistry, branch: str, chat_id: int = 1) -> CommandContext:
    project_name = project_registry.get_default_project_name()
    store = InMemoryJobStore()
    store.create(
        Job(
            id="job-succeeded",
            request=JobRequest(
                project=project_name,
                model=ModelName.CLAUDE,
                instruction="x",
                chat_id=chat_id,
                requested_by=chat_id,
            ),
            status=JobStatus.SUCCEEDED,
            branch=branch,
            commit_hash="abc1234",
        )
    )
    return CommandContext(
        job_store=store,
        default_model=ModelName.CLAUDE,
        project_registry=project_registry,
        model_preferences=InMemoryModelPreferenceStore(default_model=ModelName.CLAUDE),
        project_name=project_name,
        git_service=Mock(),
        git_remote_name="origin",
        conversation_store=None,
        confirmation_store=InMemoryConfirmationStore(),
        advanced_settings_store=None,
    )


def test_discard_requires_branch_argument(project_registry: ProjectRegistry):
    ctx = _ctx_with_branch(project_registry, "remote-fix")
    text = DiscardCommand().execute(TelegramMessage(chat_id=1, user_id=1, text="/discard"), ctx)
    assert "Usage" in text


def test_discard_rejects_unknown_branch(project_registry: ProjectRegistry):
    ctx = _ctx_with_branch(project_registry, "remote-fix")
    text = DiscardCommand().execute(
        TelegramMessage(chat_id=1, user_id=1, text="/discard remote-other"), ctx
    )
    assert "not a succeeded Job branch" in text
    ctx.git_service.delete_local_branches.assert_not_called()


def test_discard_rejects_main_branch(project_registry: ProjectRegistry):
    ctx = _ctx_with_branch(project_registry, "remote-fix")
    text = DiscardCommand().execute(TelegramMessage(chat_id=1, user_id=1, text="/discard main"), ctx)
    assert "integration branch" in text


def test_discard_sets_confirmation_and_shows_buttons(project_registry: ProjectRegistry):
    ctx = _ctx_with_branch(project_registry, "remote-fix")
    registry = CommandRegistry([DiscardCommand()])

    response = registry.dispatch_rich(
        TelegramMessage(chat_id=1, user_id=1, text="/discard remote-fix"), ctx
    )

    assert response is not None
    assert "Pending action" in response.text
    assert "remote-fix" in response.text
    assert response.inline_buttons == [
        [InlineButton("Yes", "__discard_confirm__:yes"), InlineButton("No", "__discard_confirm__:no")]
    ]
    ctx.git_service.delete_local_branches.assert_not_called()


def test_discard_confirmation_no_cancels(project_registry: ProjectRegistry):
    ctx = _ctx_with_branch(project_registry, "remote-fix")
    registry = CommandRegistry([DiscardCommand()])
    registry.dispatch(TelegramMessage(chat_id=1, user_id=1, text="/discard remote-fix"), ctx)

    text = registry.dispatch(
        TelegramMessage(chat_id=1, user_id=1, text="__discard_confirm__:no"), ctx
    )

    assert "cancelled" in (text or "")
    ctx.git_service.delete_local_branches.assert_not_called()


def test_discard_confirmation_yes_deletes_branch_and_worktree(project_registry: ProjectRegistry):
    ctx = _ctx_with_branch(project_registry, "remote-fix")
    ctx.git_service.list_local_branches_matching.return_value = ["remote-fix"]
    ctx.git_service.list_remote_branches_matching.return_value = ["remote-fix"]
    registry = CommandRegistry([DiscardCommand()])
    registry.dispatch(TelegramMessage(chat_id=1, user_id=1, text="/discard remote-fix"), ctx)

    text = registry.dispatch(
        TelegramMessage(chat_id=1, user_id=1, text="__discard_confirm__:yes"), ctx
    )

    assert "Discarded branch `remote-fix`" in (text or "")
    ctx.git_service.remove_linked_worktrees_for_branches.assert_called_once()
    ctx.git_service.delete_local_branches.assert_called_once()
    ctx.git_service.delete_remote_branches.assert_called_once()


def test_cherrypick_sets_confirmation_and_shows_buttons(project_registry: ProjectRegistry):
    ctx = _ctx_with_branch(project_registry, "remote-fix")
    registry = CommandRegistry([CherryPickCommand()])

    response = registry.dispatch_rich(
        TelegramMessage(chat_id=1, user_id=1, text="/cherrypick remote-fix"), ctx
    )

    assert response is not None
    assert "Pending action" in response.text
    assert "cherry-pick" in response.text.lower()
    assert response.inline_buttons == [
        [
            InlineButton("Yes", "__cherrypick_confirm__:yes"),
            InlineButton("No", "__cherrypick_confirm__:no"),
        ]
    ]
    ctx.git_service.cherry_pick_branch_onto_main.assert_not_called()


def test_cherrypick_confirmation_yes_invokes_git_service(project_registry: ProjectRegistry):
    ctx = _ctx_with_branch(project_registry, "remote-fix")
    ctx.git_service.cherry_pick_branch_onto_main.return_value = "Cherry-pick complete: ..."
    registry = CommandRegistry([CherryPickCommand()])
    registry.dispatch(TelegramMessage(chat_id=1, user_id=1, text="/cherrypick remote-fix"), ctx)

    text = registry.dispatch(
        TelegramMessage(chat_id=1, user_id=1, text="__cherrypick_confirm__:yes"), ctx
    )

    assert "Cherry-pick complete" in (text or "")
    ctx.git_service.cherry_pick_branch_onto_main.assert_called_once()


def test_cherrypick_confirmation_no_cancels(project_registry: ProjectRegistry):
    ctx = _ctx_with_branch(project_registry, "remote-fix")
    registry = CommandRegistry([CherryPickCommand()])
    registry.dispatch(TelegramMessage(chat_id=1, user_id=1, text="/cherrypick remote-fix"), ctx)

    text = registry.dispatch(
        TelegramMessage(chat_id=1, user_id=1, text="__cherrypick_confirm__:no"), ctx
    )

    assert "cancelled" in (text or "")
    ctx.git_service.cherry_pick_branch_onto_main.assert_not_called()


def test_tapping_cherrypick_button_while_discard_pending_starts_over(
    project_registry: ProjectRegistry,
):
    # Regression: tapping a different result-card action button while one is pending must start
    # the new action rather than silently cancelling the pending one.
    ctx = _ctx_with_branch(project_registry, "remote-fix")
    registry = CommandRegistry([DiscardCommand(), CherryPickCommand()])
    registry.dispatch(TelegramMessage(chat_id=1, user_id=1, text="/discard remote-fix"), ctx)

    text = registry.dispatch(
        TelegramMessage(chat_id=1, user_id=1, text="/cherrypick remote-fix"), ctx
    )

    assert "Pending action" in (text or "")
    assert "cherry-pick" in (text or "").lower()
    # The pending is now the cherry-pick, so its confirm runs the cherry-pick.
    ctx.git_service.cherry_pick_branch_onto_main.return_value = "Cherry-pick complete"
    confirm = registry.dispatch(
        TelegramMessage(chat_id=1, user_id=1, text="__cherrypick_confirm__:yes"), ctx
    )
    assert "Cherry-pick complete" in (confirm or "")
    ctx.git_service.delete_local_branches.assert_not_called()


def test_discard_blocked_while_branch_op_in_flight(project_registry: ProjectRegistry):
    from app.git.branch_ops_lock import acquire_branch_op, release_branch_op

    ctx = _ctx_with_branch(project_registry, "remote-fix")
    entry = ctx.project_registry.get(ctx.project_name)
    key = (str(entry.root_path.resolve()), "origin", "remote-fix")
    assert acquire_branch_op(key)
    try:
        registry = CommandRegistry([DiscardCommand()])
        registry.dispatch(TelegramMessage(chat_id=1, user_id=1, text="/discard remote-fix"), ctx)
        text = registry.dispatch(
            TelegramMessage(chat_id=1, user_id=1, text="__discard_confirm__:yes"), ctx
        )
        assert "already has a branch operation running" in (text or "")
        ctx.git_service.delete_local_branches.assert_not_called()
    finally:
        release_branch_op(key)
