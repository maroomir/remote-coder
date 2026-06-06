from __future__ import annotations

import re
from threading import Lock

from app.telegram.commands.base import (
    CommandContext,
    InlineButton,
    TelegramCommand,
    TelegramMessage,
    _button_rows,
    _cmd_evt,
    effective_project_name_for_chat,
    format_usage,
)


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
    _inflight_guard = Lock()
    _inflight_keys: set[tuple[str, str, str]] = set()

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

        inflight_key = (str(entry.root_path.resolve()), ctx.git_remote_name, branch)
        if not self._mark_inflight(inflight_key):
            return f"`{branch}` rebase/merge is already running. Wait for the completion message."

        ops_base = entry.worktree_base_dir / "_rebase_ops"
        try:
            if not self._remote_branch_exists(entry.root_path, branch, ctx):
                return (
                    f"`{branch}` remote branch was not found on `{ctx.git_remote_name}`. "
                    "It may have already been rebased/merged and deleted, or not pushed yet."
                )
            summary = ctx.git_service.rebase_branch_onto_main_and_merge(
                entry.root_path,
                branch,
                ctx.git_remote_name,
                ops_base,
            )
            if self._delete_rebased_branch_enabled(ctx):
                ctx.git_service.delete_remote_branches(entry.root_path, ctx.git_remote_name, [branch])
                ctx.git_service.delete_local_branches(entry.root_path, [branch])
                summary += f"\nDeleted branch `{branch}` locally and from `{ctx.git_remote_name}`."
            return summary
        except RuntimeError as exc:
            return f"/rebase failed: {exc}"
        finally:
            self._clear_inflight(inflight_key)

    @classmethod
    def _mark_inflight(cls, key: tuple[str, str, str]) -> bool:
        with cls._inflight_guard:
            if key in cls._inflight_keys:
                return False
            cls._inflight_keys.add(key)
            return True

    @classmethod
    def _clear_inflight(cls, key: tuple[str, str, str]) -> None:
        with cls._inflight_guard:
            cls._inflight_keys.discard(key)

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
            remote_branch_list = ctx.git_service.list_remote_branches_matching(entry.root_path, ctx.git_remote_name, "")
        except RuntimeError:
            return []
        if not isinstance(remote_branch_list, list):
            return []
        remote_branches = set(remote_branch_list)
        excluded = {main_branch, "main", "master"}
        return [branch for branch in branches if branch not in excluded and branch in remote_branches]

    def _remote_branch_exists(self, root_path, branch: str, ctx: CommandContext) -> bool:
        try:
            remote_branches = ctx.git_service.list_remote_branches_matching(root_path, ctx.git_remote_name, "")
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
            summary = ctx.git_service.pull_repository(entry.root_path, ctx.git_remote_name)
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
            branches = self._list_pr_candidates(message, ctx)
            if not branches:
                return "No branch is available for PR creation. Specify one with /pr <branch>."
            return "Choose a branch for the PR."
        from app.git.service import GitWorktreeService

        err = GitWorktreeService.validate_branch_token(branch)
        if err:
            return err

        project_name = effective_project_name_for_chat(ctx, message.chat_id)
        if not project_name:
            return "No project is registered. Add one in /projects."
        entry = ctx.project_registry.get(project_name)
        if not entry or not entry.enabled:
            return f"Project not found or disabled: {project_name}"

        try:
            base_branch = ctx.git_service.resolve_integrate_branch(entry.root_path)
        except RuntimeError as exc:
            return f"/pr failed: {exc}"

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
            return f"/pr failed: {exc}"

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
        from app.git.service import GitWorktreeService

        excluded = {main_branch, "main", "master"}
        return [
            branch
            for branch in branches
            if branch not in excluded and GitWorktreeService.validate_branch_token(branch) is None
        ]

    def _build_pr_content(
        self,
        branch: str,
        project_name: str,
        chat_id: int,
        ctx: CommandContext,
    ) -> tuple[str, str]:
        if ctx.conversation_store is None:
            return _branch_to_pr_title(branch), f"Work branch: `{branch}`"

        entries = ctx.conversation_store.get_entries_for_branch(project_name, chat_id, branch)
        if not entries:
            return _branch_to_pr_title(branch), f"Work branch: `{branch}`"

        title = _ascii_pr_text(entries[0][0], _branch_to_pr_title(branch))[:70].rstrip()

        body_parts: list[str] = [f"Work branch: `{branch}`\n\n", "## Work request\n"]
        for i, (user_text, job_result) in enumerate(entries, 1):
            if len(entries) > 1:
                body_parts.append(f"### Request {i}\n")
            safe_user_text = _ascii_pr_text(
                user_text,
                "Request omitted because it contains non-ASCII text.",
            )
            body_parts.append(f"**Request:** {safe_user_text}\n")
            if job_result:
                safe_job_result = _ascii_pr_text(
                    job_result,
                    "AI result omitted because it contains non-ASCII text.",
                )
                body_parts.append(f"\n**AI result:**\n{safe_job_result}\n")
            if i < len(entries):
                body_parts.append("\n---\n")

        return title, "\n".join(body_parts)
