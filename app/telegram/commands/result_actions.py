from __future__ import annotations

from app.git.branch_ops_lock import acquire_branch_op, release_branch_op
from app.telegram.commands.base import (
    CommandContext,
    ConfirmableCommand,
    InlineButton,
    TelegramMessage,
    effective_git_remote_name,
    effective_project_name_for_chat,
    format_usage,
)
from app.telegram.confirmations import PendingConfirmation

DISCARD_CONFIRM_YES = "__discard_confirm__:yes"
DISCARD_CONFIRM_NO = "__discard_confirm__:no"
CHERRYPICK_CONFIRM_YES = "__cherrypick_confirm__:yes"
CHERRYPICK_CONFIRM_NO = "__cherrypick_confirm__:no"


def _resolve_scoped_branch(
    message: TelegramMessage, ctx: CommandContext, branch: str
) -> tuple[str, object] | str:
    """Validate that `branch` is a succeeded job branch in this project/chat.

    Returns (project_name, project_entry) on success, or an error string the caller returns.
    """
    from app.git.service import GitWorktreeService

    err = GitWorktreeService.validate_branch_token(branch)
    if err:
        return err
    if branch in {"main", "master"}:
        return f"`{branch}` is the integration branch and cannot be targeted here."

    project_name = effective_project_name_for_chat(ctx, message.chat_id)
    if not project_name:
        return "No project is registered. Add one in /projects."
    entry = ctx.project_registry.get(project_name)
    if not entry or not entry.enabled:
        return f"Project not found or disabled: {project_name}"

    succeeded_branches = ctx.job_store.list_succeeded_branches_for_project_chat(
        project_name, message.chat_id
    )
    if branch not in succeeded_branches:
        return f"`{branch}` is not a succeeded Job branch for this project and chat."
    return project_name, entry


def _revalidate_scope(message: TelegramMessage, ctx: CommandContext, branch: str) -> str | None:
    """Re-check branch scope at confirm time (the pending was set earlier).

    Returns an error string to send back, or None when the branch is still valid and in scope.
    """
    resolved = _resolve_scoped_branch(message, ctx, branch)
    return resolved if isinstance(resolved, str) else None


class DiscardCommand(ConfirmableCommand):
    name = "/discard"
    menu_text = "Discard a job branch and its worktree"
    # No description so this per-branch, button-driven action stays out of the slash autocomplete
    # menu; it is reachable from the result-card button and by typing /discard <branch> directly.
    description = None

    def execute(self, message: TelegramMessage, ctx: CommandContext) -> str:
        tokens = message.text.strip().split()
        if len(tokens) != 2:
            return format_usage("/discard", "/discard <branch>")
        branch = tokens[1]
        resolved = _resolve_scoped_branch(message, ctx, branch)
        if isinstance(resolved, str):
            return resolved

        ctx.confirmation_store.set(
            effective_project_name_for_chat(ctx, message.chat_id),
            message.chat_id,
            PendingConfirmation(command_name=self.name, action=branch),
        )
        return (
            f"Pending action: delete branch `{branch}` locally, from "
            f"`{effective_git_remote_name(ctx)}`, and remove its worktree.\n"
            "Choose whether to run it."
        )

    def get_inline_buttons(
        self,
        message: TelegramMessage | None = None,
        ctx: CommandContext | None = None,
    ) -> list[list[InlineButton]] | None:
        if message is None or ctx is None:
            return None
        pending = ctx.confirmation_store.get(
            effective_project_name_for_chat(ctx, message.chat_id),
            message.chat_id,
        )
        if pending is None or pending.command_name != self.name:
            return None
        return [[InlineButton("Yes", DISCARD_CONFIRM_YES), InlineButton("No", DISCARD_CONFIRM_NO)]]

    def confirm(
        self,
        message: TelegramMessage,
        ctx: CommandContext,
        pending: PendingConfirmation,
    ) -> str:
        branch = pending.action
        if message.text.strip() != DISCARD_CONFIRM_YES:
            return f"Discarding branch `{branch}` was cancelled."

        scope_error = _revalidate_scope(message, ctx, branch)
        if scope_error is not None:
            return scope_error
        project_name = effective_project_name_for_chat(ctx, message.chat_id)
        entry = ctx.project_registry.get(project_name)

        remote = effective_git_remote_name(ctx)
        inflight_key = (str(entry.root_path.resolve()), remote, branch)
        if not acquire_branch_op(inflight_key):
            return f"`{branch}` already has a branch operation running. Wait for it to finish."
        try:
            ctx.git_service.remove_linked_worktrees_for_branches(entry.root_path, [branch])
            local = ctx.git_service.list_local_branches_matching(entry.root_path, branch)
            if branch in local:
                ctx.git_service.delete_local_branches(entry.root_path, [branch])
            remote_branches = ctx.git_service.list_remote_branches_matching(
                entry.root_path, remote, branch
            )
            if branch in remote_branches:
                ctx.git_service.delete_remote_branches(entry.root_path, remote, [branch])
            return f"Discarded branch `{branch}` (local, `{remote}`, and worktree)."
        except RuntimeError as exc:
            return f"/discard failed: {exc}"
        finally:
            release_branch_op(inflight_key)


class CherryPickCommand(ConfirmableCommand):
    name = "/cherrypick"
    menu_text = "Cherry-pick a job branch commit onto main"
    # No description so this per-branch, button-driven action stays out of the slash autocomplete
    # menu; it is reachable from the result-card button and by typing /cherrypick <branch>.
    description = None

    def execute(self, message: TelegramMessage, ctx: CommandContext) -> str:
        tokens = message.text.strip().split()
        if len(tokens) != 2:
            return format_usage("/cherrypick", "/cherrypick <branch>")
        branch = tokens[1]
        resolved = _resolve_scoped_branch(message, ctx, branch)
        if isinstance(resolved, str):
            return resolved

        ctx.confirmation_store.set(
            effective_project_name_for_chat(ctx, message.chat_id),
            message.chat_id,
            PendingConfirmation(command_name=self.name, action=branch),
        )
        return (
            f"Pending action: cherry-pick the latest commit of `{branch}` onto main and "
            f"push to `{effective_git_remote_name(ctx)}`.\nChoose whether to run it."
        )

    def get_inline_buttons(
        self,
        message: TelegramMessage | None = None,
        ctx: CommandContext | None = None,
    ) -> list[list[InlineButton]] | None:
        if message is None or ctx is None:
            return None
        pending = ctx.confirmation_store.get(
            effective_project_name_for_chat(ctx, message.chat_id),
            message.chat_id,
        )
        if pending is None or pending.command_name != self.name:
            return None
        return [
            [
                InlineButton("Yes", CHERRYPICK_CONFIRM_YES),
                InlineButton("No", CHERRYPICK_CONFIRM_NO),
            ]
        ]

    def confirm(
        self,
        message: TelegramMessage,
        ctx: CommandContext,
        pending: PendingConfirmation,
    ) -> str:
        branch = pending.action
        if message.text.strip() != CHERRYPICK_CONFIRM_YES:
            return f"Cherry-pick of `{branch}` was cancelled."

        scope_error = _revalidate_scope(message, ctx, branch)
        if scope_error is not None:
            return scope_error
        project_name = effective_project_name_for_chat(ctx, message.chat_id)
        entry = ctx.project_registry.get(project_name)

        remote = effective_git_remote_name(ctx)
        ops_base = entry.worktree_base_dir / "_rebase_ops"
        inflight_key = (str(entry.root_path.resolve()), remote, branch)
        if not acquire_branch_op(inflight_key):
            return f"`{branch}` already has a branch operation running. Wait for it to finish."
        try:
            return ctx.git_service.cherry_pick_branch_onto_main(
                entry.root_path,
                branch,
                remote,
                ops_base,
            )
        except RuntimeError as exc:
            return f"/cherrypick failed: {exc}"
        finally:
            release_branch_op(inflight_key)
