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
    description = "현재 브랜치를 확인하거나 로컬 브랜치로 전환합니다"

    def execute(self, message: TelegramMessage, ctx: CommandContext) -> str:
        tokens = message.text.strip().split()
        if len(tokens) > 2:
            return format_usage("/branch", "/branch <브랜치이름>")

        project_name = effective_project_name_for_chat(ctx, message.chat_id)
        if not project_name:
            return "등록된 프로젝트가 없습니다. /projects 로 등록하세요."
        entry = ctx.project_registry.get(project_name)
        if not entry or not entry.enabled:
            return f"프로젝트를 찾을 수 없거나 비활성화되어 있습니다: {project_name}"

        root = entry.root_path

        if len(tokens) == 1:
            try:
                current = ctx.git_service.get_current_branch(root)
            except RuntimeError as exc:
                return f"/branch 실패: {exc}"
            return f"프로젝트: {project_name}\n현재 브랜치: {current}"

        branch = tokens[1]
        from app.git.service import GitWorktreeService

        err = GitWorktreeService.validate_branch_token(branch)
        if err:
            return err

        if not ctx.git_service.local_branch_exists(root, branch):
            return f"브랜치가 없습니다: `{branch}` (로컬에만 전환 가능합니다)"

        try:
            ctx.git_service.switch_branch(root, branch)
        except RuntimeError as exc:
            return f"/branch 실패: {exc}"
        return f"프로젝트: {project_name}\n`{branch}` 로 전환했습니다 (git switch)."

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
    description = "브랜치를 main 기준으로 rebase하고 push합니다"
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
                return "리베이스할 브랜치가 없습니다. /rebase <branch> 로 직접 지정할 수 있습니다."
            return "리베이스할 브랜치를 선택하세요."

        project_name = effective_project_name_for_chat(ctx, message.chat_id)
        if not project_name:
            return "등록된 프로젝트가 없습니다. /projects 로 등록하세요."
        entry = ctx.project_registry.get(project_name)
        if not entry or not entry.enabled:
            return f"프로젝트를 찾을 수 없거나 비활성화되어 있습니다: {project_name}"

        inflight_key = (str(entry.root_path.resolve()), ctx.git_remote_name, branch)
        if not self._mark_inflight(inflight_key):
            return f"`{branch}` rebase/병합이 이미 진행 중입니다. 완료 메시지를 기다려 주세요."

        ops_base = entry.worktree_base_dir / "_rebase_ops"
        try:
            if not self._remote_branch_exists(entry.root_path, branch, ctx):
                return (
                    f"`{branch}` 원격 브랜치를 `{ctx.git_remote_name}`에서 찾을 수 없습니다. "
                    "이미 rebase/병합 후 삭제되었거나 아직 push되지 않은 브랜치일 수 있습니다."
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
                summary += f"\n브랜치 `{branch}`를 로컬과 `{ctx.git_remote_name}`에서 삭제했습니다."
            return summary
        except RuntimeError as exc:
            return f"/rebase 실패: {exc}"
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
    return slug.replace("-", " ").strip() or branch


class PullCommand(TelegramCommand):
    name = "/pull"
    menu_text = "원격 저장소의 모든 브랜치 pull"
    description = "원격 브랜치 정보를 가져오고 현재 브랜치를 pull합니다"

    def execute(self, message: TelegramMessage, ctx: CommandContext) -> str:
        project_name = effective_project_name_for_chat(ctx, message.chat_id)
        if not project_name:
            return "등록된 프로젝트가 없습니다. /projects 로 등록하세요."

        entry = ctx.project_registry.get(project_name)
        if not entry or not entry.enabled:
            return f"프로젝트를 찾을 수 없거나 비활성화되어 있습니다: {project_name}"

        try:
            summary = ctx.git_service.pull_repository(entry.root_path, ctx.git_remote_name)
            _cmd_evt.info("pull success project=%s", project_name, chat_id=message.chat_id)
            return f"✅ {project_name}: {summary}"
        except RuntimeError as exc:
            _cmd_evt.error("pull failed project=%s err=%s", project_name, str(exc), chat_id=message.chat_id)
            return f"❌ {project_name} pull 실패: {exc}"


class PrCommand(TelegramCommand):
    """적용 프로젝트 저장소의 브랜치를 GitHub Pull Request로 올립니다."""

    name = "/pr"
    menu_text = "PR을 올릴 브랜치를 선택하세요."
    description = "선택한 브랜치로 GitHub Pull Request를 만듭니다"

    def execute(self, message: TelegramMessage, ctx: CommandContext) -> str:
        tokens = message.text.strip().split()
        if len(tokens) > 2:
            return format_usage("/pr", "/pr <branch>")
        if len(tokens) == 2:
            branch = tokens[1]
        else:
            branches = self._list_pr_candidates(message, ctx)
            if not branches:
                return "PR을 올릴 브랜치가 없습니다. /pr <branch> 로 직접 지정할 수 있습니다."
            return "PR을 올릴 브랜치를 선택하세요."

        project_name = effective_project_name_for_chat(ctx, message.chat_id)
        if not project_name:
            return "등록된 프로젝트가 없습니다. /projects 로 등록하세요."
        entry = ctx.project_registry.get(project_name)
        if not entry or not entry.enabled:
            return f"프로젝트를 찾을 수 없거나 비활성화되어 있습니다: {project_name}"

        try:
            base_branch = ctx.git_service.resolve_integrate_branch(entry.root_path)
        except RuntimeError as exc:
            return f"/pr 실패: {exc}"

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
            return f"/pr 실패: {exc}"

        return f"PR이 생성되었습니다:\n{pr_url}"

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
        excluded = {main_branch, "main", "master"}
        return [branch for branch in branches if branch not in excluded]

    def _build_pr_content(
        self,
        branch: str,
        project_name: str,
        chat_id: int,
        ctx: CommandContext,
    ) -> tuple[str, str]:
        if ctx.conversation_store is None:
            return _branch_to_pr_title(branch), f"작업 브랜치: `{branch}`"

        entries = ctx.conversation_store.get_entries_for_branch(project_name, chat_id, branch)
        if not entries:
            return _branch_to_pr_title(branch), f"작업 브랜치: `{branch}`"

        title = entries[0][0][:70].rstrip()

        body_parts: list[str] = ["## 작업 요청\n"]
        for i, (user_text, job_result) in enumerate(entries, 1):
            if len(entries) > 1:
                body_parts.append(f"### 요청 {i}\n")
            body_parts.append(f"**요청:** {user_text}\n")
            if job_result:
                body_parts.append(f"\n**AI 결과:**\n{job_result}\n")
            if i < len(entries):
                body_parts.append("\n---\n")

        return title, "\n".join(body_parts)
