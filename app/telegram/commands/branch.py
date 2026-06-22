from __future__ import annotations

import re

from app.git.branch_ops_lock import acquire_branch_op, release_branch_op
from app.telegram.commands.base import (
    CommandContext,
    InlineButton,
    TelegramCommand,
    TelegramMessage,
    _button_rows,
    _cmd_evt,
    effective_git_remote_name,
    effective_project_name_for_chat,
    format_usage,
)
from app.jobs.pr_content import build_pr_body
from app.telegram.i18n import ui_message


_MISSING_GH_ERROR = "GitHub CLI (gh) is not installed or not available on PATH."


def _format_pr_error(exc: RuntimeError) -> str:
    message = str(exc)
    if _MISSING_GH_ERROR in message:
        return ui_message(
            "pr.gh_missing",
            "/pr failed: GitHub CLI (gh) is not installed or not available on PATH.\n\n"
            "To create PRs from Telegram:\n"
            "1. Install GitHub CLI:\n"
            "   - macOS: `brew install gh`\n"
            "   - Windows: `winget install --id GitHub.cli`\n"
            "   - Ubuntu/Debian: `sudo apt install gh`\n"
            "2. Sign in: `gh auth login`\n"
            "3. Restart Remote AI Coder: `remote-coder up`",
        )
    return f"/pr failed: {message}"


class BranchCommand(TelegramCommand):
    name = "/branch"
    description = "Show the current branch or switch to a local branch"

    def execute(self, message: TelegramMessage, ctx: CommandContext) -> str:
        tokens = message.text.strip().split()
        if len(tokens) > 2:
            return format_usage("/branch", "/branch <branch>")

        project_name = effective_project_name_for_chat(ctx, message.chat_id)
        if not project_name:
            return "No project is registered. Add one in /projects."
        entry = ctx.project_registry.get(project_name)
        if not entry or not entry.enabled:
            return f"Project not found or disabled: {project_name}"

        root = entry.root_path

        if len(tokens) == 1:
            try:
                current = ctx.git_service.get_current_branch(root)
            except RuntimeError as exc:
                return f"/branch failed: {exc}"
            return f"Project: {project_name}\nCurrent branch: {current}"

        branch = tokens[1]
        from app.git.service import GitWorktreeService

        err = GitWorktreeService.validate_branch_token(branch)
        if err:
            return err

        if not ctx.git_service.local_branch_exists(root, branch):
            return f"Branch not found: `{branch}` (only local branches can be selected)"

        try:
            ctx.git_service.switch_branch(root, branch)
        except RuntimeError as exc:
            return f"/branch failed: {exc}"
        return f"Project: {project_name}\n`{branch}` selected (git switch)."

    def get_inline_buttons(
        self,
        message: TelegramMessage | None = None,
        ctx: CommandContext | None = None,
    ) -> list[list[InlineButton]] | None:
        if message is None or ctx is None:
            return None
        if len(message.text.strip().split()) != 1:
            return None
        project_name = effective_project_name_for_chat(ctx, message.chat_id)
        if not project_name:
            return None
        entry = ctx.project_registry.get(project_name)
        if not entry or not entry.enabled:
            return None
        try:
            branches = ctx.git_service.list_local_branches(entry.root_path)
        except RuntimeError:
            return None
        if not isinstance(branches, list):
            return None
        buttons = [InlineButton(branch, f"/branch {branch}") for branch in branches]
        return _button_rows(buttons, per_row=1) if buttons else None


class RebaseCommand(TelegramCommand):
    name = "/rebase"
    description = "Rebase a branch onto main and push it"

    def execute(self, message: TelegramMessage, ctx: CommandContext) -> str:
        tokens = message.text.strip().split()
        if len(tokens) > 2:
            return format_usage("/rebase", "/rebase <branch>")
        if len(tokens) == 2:
            branch = tokens[1]
            from app.git.service import GitWorktreeService

            err = GitWorktreeService.validate_branch_token(branch)
            if err:
                return err
        else:
            branches = self._list_rebase_candidates(message, ctx)
            if not branches:
                return "No branch is available to rebase. Specify one with /rebase <branch>."
            return "Choose a branch to rebase."

        project_name = effective_project_name_for_chat(ctx, message.chat_id)
        if not project_name:
            return "No project is registered. Add one in /projects."
        entry = ctx.project_registry.get(project_name)
        if not entry or not entry.enabled:
            return f"Project not found or disabled: {project_name}"

        inflight_key = (str(entry.root_path.resolve()), effective_git_remote_name(ctx), branch)
        if not acquire_branch_op(inflight_key):
            return f"`{branch}` rebase/merge is already running. Wait for the completion message."

        ops_base = entry.worktree_base_dir / "_rebase_ops"
        try:
            if not self._remote_branch_exists(entry.root_path, branch, ctx):
                return (
                    f"`{branch}` remote branch was not found on `{effective_git_remote_name(ctx)}`. "
                    "It may have already been rebased/merged and deleted, or not pushed yet."
                )
            summary = ctx.git_service.rebase_branch_onto_main_and_merge(
                entry.root_path,
                branch,
                effective_git_remote_name(ctx),
                ops_base,
            )
            if self._delete_rebased_branch_enabled(ctx):
                ctx.git_service.delete_remote_branches(entry.root_path, effective_git_remote_name(ctx), [branch])
                ctx.git_service.delete_local_branches(entry.root_path, [branch])
                summary += f"\nDeleted branch `{branch}` locally and from `{effective_git_remote_name(ctx)}`."
            return summary
        except RuntimeError as exc:
            return f"/rebase failed: {exc}"
        finally:
            release_branch_op(inflight_key)

    def _delete_rebased_branch_enabled(self, ctx: CommandContext) -> bool:
        if ctx.advanced_settings_store is None:
            return True
        return ctx.advanced_settings_store.get().delete_rebased_branch_enabled

    def get_inline_buttons(
        self,
        message: TelegramMessage | None = None,
        ctx: CommandContext | None = None,
    ) -> list[list[InlineButton]] | None:
        if message is None or ctx is None:
            return None
        if len(message.text.strip().split()) != 1:
            return None
        branches = self._list_rebase_candidates(message, ctx)
        buttons = [InlineButton(branch, f"/rebase {branch}") for branch in branches]
        return _button_rows(buttons, per_row=1) if buttons else None

    def _list_rebase_candidates(self, message: TelegramMessage, ctx: CommandContext) -> list[str]:
        project_name = effective_project_name_for_chat(ctx, message.chat_id)
        if not project_name:
            return []
        entry = ctx.project_registry.get(project_name)
        if not entry or not entry.enabled:
            return []
        try:
            main_branch = ctx.git_service.resolve_integrate_branch(entry.root_path)
            branches = ctx.git_service.list_local_branches(entry.root_path)
        except RuntimeError:
            return []
        if not isinstance(branches, list):
            return []
        try:
            remote_branch_list = ctx.git_service.list_remote_branches_matching(entry.root_path, effective_git_remote_name(ctx), "")
        except RuntimeError:
            return []
        if not isinstance(remote_branch_list, list):
            return []
        remote_branches = set(remote_branch_list)
        excluded = {main_branch, "main", "master"}
        return [branch for branch in branches if branch not in excluded and branch in remote_branches]

    def _remote_branch_exists(self, root_path, branch: str, ctx: CommandContext) -> bool:
        try:
            remote_branches = ctx.git_service.list_remote_branches_matching(root_path, effective_git_remote_name(ctx), "")
        except RuntimeError:
            return False
        if not isinstance(remote_branches, list):
            return False
        return branch in remote_branches


def _branch_to_pr_title(branch: str) -> str:
    slug = branch
    if slug.startswith("remote-"):
        slug = slug[len("remote-"):]
    slug = re.sub(r"-\d{8}-\d{6}$", "", slug)
    title = slug.replace("-", " ").strip()
    if title and title.isascii():
        return title
    return "remote coder changes"


def _ascii_pr_text(text: str, fallback: str) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    if normalized and normalized.isascii():
        return normalized
    return fallback


class PullCommand(TelegramCommand):
    name = "/pull"
    menu_text = "Pull all remote branch updates"
    description = "Fetch remote branches and pull the current branch"

    def execute(self, message: TelegramMessage, ctx: CommandContext) -> str:
        project_name = effective_project_name_for_chat(ctx, message.chat_id)
        if not project_name:
            return "No project is registered. Add one in /projects."

        entry = ctx.project_registry.get(project_name)
        if not entry or not entry.enabled:
            return f"Project not found or disabled: {project_name}"

        try:
            summary = ctx.git_service.pull_repository(entry.root_path, effective_git_remote_name(ctx))
            _cmd_evt.info("pull success project=%s", project_name, chat_id=message.chat_id)
            return f"✅ {project_name}: {summary}"
        except RuntimeError as exc:
            _cmd_evt.error("pull failed project=%s err=%s", project_name, str(exc), chat_id=message.chat_id)
            return f"❌ {project_name} pull failed: {exc}"


class PrCommand(TelegramCommand):
    name = "/pr"
    menu_text = "Choose a branch for the PR."
    description = "Create a GitHub Pull Request for a selected branch"

    def execute(self, message: TelegramMessage, ctx: CommandContext) -> str:
        tokens = message.text.strip().split()
        if len(tokens) > 2:
            return format_usage("/pr", "/pr <branch>")
        if len(tokens) == 2:
            branch = tokens[1]
        else:
            try:
                branches = self._load_pr_candidates(message, ctx)
            except RuntimeError as exc:
                return _format_pr_error(exc)
            if not branches:
                return ui_message(
                    "pr.no_candidates",
                    "No succeeded Job branch from this project and chat remains "
                    "on `{remote}`.",
                    remote=effective_git_remote_name(ctx),
                )
            return "Choose a branch for the PR."
        from app.git.service import GitWorktreeService

        err = GitWorktreeService.validate_branch_token(branch)
        if err:
            return err
        if branch in {"main", "master"}:
            return f"`{branch}` is not a succeeded Job branch for this project and chat."

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
            return ui_message(
                "pr.not_job_branch",
                "`{branch}` is not a succeeded Job branch for this project and chat.",
                branch=branch,
            )

        remote = effective_git_remote_name(ctx)
        try:
            remote_branches = ctx.git_service.list_remote_branches_matching(
                entry.root_path, remote, ""
            )
        except RuntimeError as exc:
            return _format_pr_error(exc)
        if branch not in remote_branches:
            return ui_message(
                "pr.remote_branch_missing",
                "Remote branch `{branch}` was not found on `{remote}`. "
                "It may have been deleted after the Job completed.",
                branch=branch,
                remote=remote,
            )

        try:
            base_branch = ctx.git_service.resolve_integrate_branch(entry.root_path)
        except RuntimeError as exc:
            return _format_pr_error(exc)

        title, body = self._build_pr_content(branch, project_name, message.chat_id, ctx)

        try:
            pr_url = ctx.git_service.create_github_pr(
                entry.root_path,
                branch,
                base_branch,
                title,
                body,
            )
        except RuntimeError as exc:
            return _format_pr_error(exc)

        return f"PR created:\n{pr_url}"

    def get_inline_buttons(
        self,
        message: TelegramMessage | None = None,
        ctx: CommandContext | None = None,
    ) -> list[list[InlineButton]] | None:
        if message is None or ctx is None:
            return None
        if len(message.text.strip().split()) != 1:
            return None
        branches = self._list_pr_candidates(message, ctx)
        buttons = [InlineButton(branch, f"/pr {branch}") for branch in branches]
        return _button_rows(buttons, per_row=1) if buttons else None

    def _list_pr_candidates(self, message: TelegramMessage, ctx: CommandContext) -> list[str]:
        try:
            return self._load_pr_candidates(message, ctx)
        except RuntimeError:
            return []

    def _load_pr_candidates(self, message: TelegramMessage, ctx: CommandContext) -> list[str]:
        project_name = effective_project_name_for_chat(ctx, message.chat_id)
        if not project_name:
            return []
        entry = ctx.project_registry.get(project_name)
        if not entry or not entry.enabled:
            return []
        branches = ctx.job_store.list_succeeded_branches_for_project_chat(
            project_name, message.chat_id
        )
        remote_branches = set(
            ctx.git_service.list_remote_branches_matching(
                entry.root_path, effective_git_remote_name(ctx), ""
            )
        )
        from app.git.service import GitWorktreeService

        return [
            branch
            for branch in branches
            if branch in remote_branches
            and branch not in {"main", "master"}
            and GitWorktreeService.validate_branch_token(branch) is None
        ]

    def _build_pr_content(
        self,
        branch: str,
        project_name: str,
        chat_id: int,
        ctx: CommandContext,
    ) -> tuple[str, str]:
        entries: list[tuple[str, str | None]] = []
        if ctx.conversation_store is not None:
            entries = ctx.conversation_store.get_entries_for_branch(project_name, chat_id, branch)

        job = ctx.job_store.get_latest_succeeded_job_for_branch(project_name, chat_id, branch)

        title = (
            _ascii_pr_text(entries[0][0], _branch_to_pr_title(branch))[:70].rstrip()
            if entries
            else _branch_to_pr_title(branch)
        )
        body = build_pr_body(branch, entries, job)
        return title, body
