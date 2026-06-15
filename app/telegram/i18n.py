from __future__ import annotations

import re
from dataclasses import dataclass

from app.models import UiLanguage


class UiMessage(str):
    def __new__(
        cls,
        key: str,
        default_template: str,
        params: dict[str, object] | None = None,
    ) -> "UiMessage":
        params = dict(params or {})
        default = _format_template(default_template, params, UiLanguage.ENGLISH)
        obj = str.__new__(cls, default)
        obj.key = key
        obj.default_template = default_template
        obj.params = params
        return obj

    key: str
    default_template: str
    params: dict[str, object]

    def render(self, language: UiLanguage) -> str:
        if language is UiLanguage.ENGLISH:
            return str(self)
        template = _MESSAGE_CATALOG_KO.get(self.key, self.default_template)
        return _format_template(template, self.params, language)


class _SafeFormatDict(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _format_template(template: str, params: dict[str, object], language: UiLanguage) -> str:
    escaped_params = {
        key: value.render(language) if isinstance(value, UiMessage) else str(value)
        for key, value in params.items()
    }
    return template.format_map(_SafeFormatDict(escaped_params))


def ui_message(key: str, default_template: str, **params: object) -> UiMessage:
    return UiMessage(key, default_template, params)


def language_from_settings_store(settings_store) -> UiLanguage:
    if settings_store is None:
        return UiLanguage.ENGLISH
    return settings_store.get().ui_language


@dataclass(frozen=True, slots=True)
class InstructionFrameLabels:
    prev_context_open: str
    prev_context_close: str
    current_request_open: str
    current_request_close: str
    reply_job_open: str
    reply_job_close: str
    reply_chain_open: str
    reply_chain_close: str
    reply_message_open: str
    reply_message_close: str
    none_absent: str


def instruction_frame_labels(language: UiLanguage) -> InstructionFrameLabels:
    if language is UiLanguage.KOREAN:
        return InstructionFrameLabels(
            prev_context_open="[이전 대화/작업 맥락]",
            prev_context_close="[/이전 대화]",
            current_request_open="[현재 요청]",
            current_request_close="[/현재 요청]",
            reply_job_open="[Reply Job 맥락]",
            reply_job_close="[/Reply Job 맥락]",
            reply_chain_open="[Reply 체인 맥락]",
            reply_chain_close="[/Reply 체인 맥락]",
            reply_message_open="[Reply 메시지 맥락]",
            reply_message_close="[/Reply 메시지 맥락]",
            none_absent="(없음)",
        )
    return InstructionFrameLabels(
        prev_context_open="[Previous conversation/job context]",
        prev_context_close="[/previous context block]",
        current_request_open="[Current request]",
        current_request_close="[/current request]",
        reply_job_open="[Reply job context]",
        reply_job_close="[/Reply job context]",
        reply_chain_open="[Reply chain context]",
        reply_chain_close="[/Reply chain context]",
        reply_message_open="[Reply message context]",
        reply_message_close="[/Reply message context]",
        none_absent="(none)",
    )


_GIT_BRANCH_VALIDATION_EN_TO_KO = {
    "Branch name is empty or too long.": "브랜치 이름이 비었거나 너무 깁니다.",
    "Branch name is not allowed.": "허용되지 않는 브랜치 이름입니다.",
    "Branch names may only use letters, numbers, /, ., _, and -.": (
        "브랜치 이름은 영문, 숫자, /, ., _, - 만 사용할 수 있습니다."
    ),
}


def localize_git_branch_validation_message(message: str, language: UiLanguage) -> str:
    if language is UiLanguage.ENGLISH:
        return message
    return _GIT_BRANCH_VALIDATION_EN_TO_KO.get(message, message)


def command_parse_error_empty_instruction_plan_ask(language: UiLanguage) -> str:
    if language is UiLanguage.KOREAN:
        return (
            "작업 지시문이 비어 있습니다.\n\n"
            "예: plan: 로그인 수정 계획 세워줘\n"
            "예: /ask JobManager 흐름 설명해줘\n"
            "예: /research webhook 보안 권장사항 조사"
        )
    return (
        "The work instruction is empty.\n\n"
        "Example: plan: outline the login refactor\n"
        "Example: /ask explain JobManager routing\n"
        "Example: /research compare webhook security guidance"
    )


def command_parse_error_empty_instruction_fix(language: UiLanguage) -> str:
    if language is UiLanguage.KOREAN:
        return (
            "수정 지시문이 비어 있습니다.\n\n"
            "예: (Job 결과에 답장) fix: 로그인 검증 버그 수정\n"
            "예: (Job 결과에 답장) /fix"
        )
    return (
        "The fix instruction is empty.\n\n"
        "Example: (reply to job result) fix: patch the login validation bug\n"
        "Example: (reply to job result) /fix"
    )


def command_parse_error_fix_requires_target(language: UiLanguage) -> str:
    if language is UiLanguage.KOREAN:
        return (
            "fix 모드는 Job 결과 메시지에 답장한 뒤 사용해야 합니다.\n\n"
            "예: (Job 결과에 답장) fix: 테스트도 추가해줘\n"
            "예: (Job 결과에 답장) /fix"
        )
    return (
        "Fix mode requires replying to a job result message.\n\n"
        "Example: (reply to job result) fix: add tests too\n"
        "Example: (reply to job result) /fix"
    )


def command_parse_error_empty_instruction(language: UiLanguage) -> str:
    return (
        "작업 지시문이 비어 있습니다."
        if language is UiLanguage.KOREAN
        else "The work instruction is empty."
    )


def command_parse_error_unknown_project(project_name: str, language: UiLanguage) -> str:
    if language is UiLanguage.KOREAN:
        return f"알 수 없는 프로젝트: {project_name}"
    return f"Unknown project: {project_name}"


def command_parse_error_disabled_project(project_name: str, language: UiLanguage) -> str:
    if language is UiLanguage.KOREAN:
        return f"비활성화된 프로젝트: {project_name}"
    return f"Disabled project: {project_name}"


def command_parse_error_no_previous_job_context(language: UiLanguage) -> str:
    return (
        "이전 작업 맥락이 없습니다. 구체적인 작업 지시를 보내주세요."
        if language is UiLanguage.KOREAN
        else "There is no previous job context. Send a specific work instruction."
    )


_TEXT_REPLACEMENTS_KO_TO_EN_RAW: tuple[tuple[str, str], ...] = (
    ("도움말", "Help"),
    ("작업 지시는 일반 메시지로 보내세요.", "Send work requests as regular messages."),
    ("옵션", "Options"),
    ("계획 모드", "plan mode"),
    ("질문 모드", "ask mode"),
    ("조사 모드", "research mode"),
    ("명령어 목록:", "Commands:"),
    ("메뉴와 프로젝트 상태를 확인합니다", "Show the menu and project status"),
    ("사용 가능한 명령어를 확인합니다", "Show available commands"),
    ("채팅의 기본 AI 모델을 확인하거나 변경합니다", "Show or change this chat's default AI model"),
    ("최근 Job 목록과 작업 상태를 조회합니다", "Show recent jobs and job status"),
    ("모델 설정과 확인 대기 상태를 초기화합니다", "Reset model settings and pending confirmations"),
    ("현재 채팅의 대화 기억 요약을 조회합니다", "Show this chat's conversation memory summary"),
    ("현재 브랜치를 확인하거나 로컬 브랜치로 전환합니다", "Show the current branch or switch to a local branch"),
    ("브랜치를 main 기준으로 rebase하고 push합니다", "Rebase a branch onto main and push it"),
    ("원격 브랜치 정보를 가져오고 현재 브랜치를 pull합니다", "Fetch remote branches and pull the current branch"),
    ("선택한 브랜치로 GitHub Pull Request를 만듭니다", "Create a GitHub Pull Request for a selected branch"),
    ("모델, 메모리, 브랜치, worktree 상태를 점검합니다", "Check model, memory, branch, and worktree status"),
    ("브랜치, worktree, 대화 기억을 확인 후 정리합니다", "Clean branches, worktrees, or conversation memory after confirmation"),
    ("진행 중인 Job을 선택해 중단합니다", "Choose and stop a running job"),
    ("이전 Job의 커밋 또는 소스를 다시 수정합니다", "Fix the source of a previous job"),
    ("수정 대상을 선택하세요.", "Choose a job to fix."),
    ("수정할 항목을 선택하세요.", "Choose a job to fix."),
    ("수정 대상 Job을 선택하세요.", "Choose a job to fix."),
    ("수정 가능한 Job이 없습니다.", "No job is available to fix."),
    ("수정 기능을 사용할 수 없습니다.", "Fix feature is not available."),
    ("커밋 메시지 재생성 미리보기", "Commit message preview"),
    ("적용하려면 확인 버튼을 누르세요.", "Use the confirmation button to apply."),
    ("커밋 메시지 수정을 취소했습니다.", "Cancelled the commit message fix."),
    ("커밋 메시지를 수정했습니다.", "Commit message updated."),
    ("커밋 메시지 수정 실패:", "Commit message fix failed:"),
    ("수정 대상으로 사용할 수 없는 Job입니다", "Job cannot be used as a fix target"),
    ("수정 대상 Job을 더 이상 사용할 수 없습니다.", "Fix target job is no longer available."),
    ("수정 작업을 백그라운드로 시작했습니다.", "Started the fix job in the background."),
    ("수정 작업을 취소했습니다.", "Cancelled the fix job."),
    ("수정 작업을 확인하세요.", "Confirm the fix job."),
    ("대상 Job", "Target Job"),
    ("원본 커밋", "Original commit"),
    ("기존 커밋을 amend 후 --force-with-lease push", "amends the existing commit and pushes with --force-with-lease"),
    ("커밋 수정 (commit)", "Fix job"),
    ("소스 수정 (source)", "Fix source"),
    ("브랜치:", "Branch:"),
    (
        "에 대한 수정 지시를 보내주세요. 다음 메시지를 그대로 지시로 사용합니다.",
        ": send the fix instruction. The next message will be used as the instruction.",
    ),
    ("계획 모드 메시지", "plan mode message"),
    ("질문 모드 메시지", "ask mode message"),
    ("조사 모드 메시지", "research mode message"),
    ("로그인 흐름 검토", "review login flow"),
    ("역할 설명", "explain the role"),
    ("기본 모델 변경", "Change the default model"),
    ("작업 상태 확인", "Check job status"),
    ("브랜치 조회 또는 전환", "Show or switch branches"),
    ("원격 브랜치 업데이트 pull", "Pull remote branch updates"),
    ("원격 저장소의 모든 브랜치 pull", "Pull all remote branch updates"),
    ("브랜치 리베이스", "Rebase a branch"),
    ("GitHub PR 열기", "Open a GitHub PR"),
    ("브랜치를 GitHub PR로 올리기", "Open a GitHub PR for a branch"),
    ("모니터링", "Monitoring"),
    ("정리 (확인 필요)", "Cleanup (confirmation)"),
    ("정리 (확인 필요)", "Cleanup (confirmation required)"),
    ("대화 기억 리포트", "Conversation memory report"),
    ("이 채팅 설정 초기화", "Reset this chat's settings"),
    ("진행 중인 작업 중단", "Stop a running job"),
    ("연결된 Job 커밋 수정", "Fix linked job commit"),
    ("인라인 메뉴", "Inline menu"),
    ("모델을 선택하세요.", "Choose a model."),
    ("모델 Provider가 선택되었습니다.", "Model provider selected."),
    ("세부 Model을 선택하세요.", "Choose a specific model."),
    ("알 수 없는 세부 Model입니다", "Unknown specific model"),
    ("모델 설정이 변경되었습니다.", "Model setting updated."),
    ("모델 설정", "Model settings"),
    ("현재 기본 모델", "Current default model"),
    ("기본 모델을", "Default model changed to"),
    ("로 변경했습니다.", "."),
    ("사용법", "Usage"),
    ("조회할 Job을 선택하세요.", "Choose a job to inspect."),
    ("조회할 수 있는 Job이 없습니다.", "No jobs are available."),
    ("해당 Job ID를 찾을 수 없습니다.", "Job ID not found."),
    ("상태", "Status"),
    ("프로젝트", "Project"),
    ("요청 모델", "Requested model"),
    ("사용 모델", "Model used"),
    ("- 모드", "- Mode"),
    ("토큰 사용량", "Token usage"),
    ("확인 불가", "unavailable"),
    ("작업 접수 완료", "Job accepted"),
    ("작업 완료", "Job completed"),
    ("작업 실패", "Job failed"),
    ("작업 중단됨", "Job cancelled"),
    ("응답 완료", "Completed"),
    ("- 시작:", "- Started:"),
    ("→ 완료:", "→ Finished:"),
    ("(소요:", "(duration:"),
    ("(경과:", "(elapsed:"),
    ("- 생성:", "- Created:"),
    ("커밋", "Commit"),
    ("변경 파일", "Changed files"),
    ("없음 (no-op)", "none (no-op)"),
    ("오류 단계", "Error stage"),
    ("실패 단계", "Failure stage"),
    ("로그 경로", "Log path"),
    ("실패 출력 요약", "Failure output summary"),
    ("오류", "Error"),
    ("현재 출력", "Current output"),
    ("AI 출력 요약", "AI output summary"),
    ("AI 응답", "AI response"),
    ("Remote AI Coder가 준비되었습니다.", "Remote AI Coder is ready."),
    ("Remote AI Coder 서버가 시작되었습니다.", "Remote AI Coder server started."),
    ("Remote AI Coder 서버 연결이 종료되었습니다.", "Remote AI Coder server connection closed."),
    ("모델", "Model"),
    ("Remote AI Coder에 오신 것을 환영합니다.", "Welcome to Remote AI Coder."),
    ("코딩 요청을 보내거나 Help를 눌러 시작하세요.", "Send a coding request or tap Help to start."),
    ("🧭 도움말", "🧭 Help"),
    ("⚙️ 옵션", "⚙️ Options"),
    ("📋 명령어 목록", "📋 Commands"),
    ("💡 예시", "💡 Examples"),
    ("🤖 AGENTS 모드 (agent)", "🤖 AGENTS mode (agent)"),
    ("📐 Plan 모드 (plan)", "📐 Plan mode (plan)"),
    ("❓ Ask 모드 (ask)", "❓ Ask mode (ask)"),
    ("🔎 Research 모드 (research)", "🔎 Research mode (research)"),
    ("🔧 Fix 모드 (fix)", "🔧 Fix mode (fix)"),
    ("💡 팁: 작업 결과에 reply 후 `fix: ...`를 보내면 그 커밋을 보완합니다.", "💡 Tip: Reply to a job result and send `fix: ...` to amend that commit."),
    ("등록 정보 없음", "not registered"),
    ("확인 실패", "check failed"),
    ("실행할 명령을 선택하세요.", "Choose a command."),
    ("확인할 모드 안내를 선택하세요.", "Choose a mode guide."),
    ("브랜치 확인", "Branch"),
    ("리베이스", "Rebase"),
    ("PR 올리기", "Open PR"),
    ("중단", "Stop"),
    ("초기화", "Reset"),
    ("뒤로", "Back"),
    ("모드별 안내", "Modes"),
    ("관리", "Manage"),
    ("리포트", "Reports"),
    ("이 채팅의 기본 모델·확인 대기 상태를 초기화했습니다.", "This chat's default model and pending confirmation were reset."),
    ("프로젝트 컨텍스트가 설정되지 않았습니다.", "No project context is configured."),
    ("관리 화면에서 프로젝트 설정을 확인하세요.", "Check the project settings in the admin UI."),
    ("관리 화면에서 활성화 상태를 확인하세요.", "Check the enabled state in the admin UI."),
    ("적용 프로젝트", "Project"),
    ("기본 모델", "Default model"),
    ("기억 리포트", "Memory report"),
    ("총 기록", "Total entries"),
    ("사용자 요청", "User requests"),
    ("Job 접수", "Jobs accepted"),
    ("Job 결과", "Job results"),
    ("최근 사용자 요청", "Latest user request"),
    ("최근 Job 결과", "Latest job result"),
    ("최근 기억", "Recent memory"),
    ("기억된 대화 기록이 없습니다.", "No conversation memory is stored."),
    ("등록된 프로젝트가 없습니다.", "No project is registered."),
    ("프로젝트를 찾을 수 없거나 비활성화되어 있습니다", "Project not found or disabled"),
    ("현재 브랜치", "Current branch"),
    ("브랜치가 없습니다", "Branch not found"),
    ("로컬에만 전환 가능합니다", "only local branches can be selected"),
    ("로 전환했습니다 (git switch).", " selected (git switch)."),
    (
        "리베이스할 브랜치가 없습니다. /rebase <branch> 로 직접 지정할 수 있습니다.",
        "No branch is available to rebase. Specify one with /rebase <branch>.",
    ),
    ("리베이스할 브랜치가 없습니다.", "No branch is available to rebase."),
    ("리베이스할 브랜치를 선택하세요.", "Choose a branch to rebase."),
    ("등록된 프로젝트가 없습니다. /projects 로 등록하세요.", "No project is registered. Add one in /projects."),
    ("브라우저에서 http://127.0.0.1:8000/projects 로 프로젝트를 등록하세요.", "Register a project at http://127.0.0.1:8000/projects."),
    ("원격 브랜치를", "remote branch on"),
    ("에서 찾을 수 없습니다.", "was not found."),
    ("이미 rebase/병합 후 삭제되었거나 아직 push되지 않은 브랜치일 수 있습니다.", "It may have already been rebased/merged and deleted, or not pushed yet."),
    ("브랜치를 로컬과", "Deleted the branch locally and from"),
    ("에서 삭제했습니다.", "."),
    ("PR을 올릴 브랜치가 없습니다.", "No branch is available for PR creation."),
    ("PR을 올릴 브랜치를 선택하세요.", "Choose a branch for the PR."),
    ("PR이 생성되었습니다:", "PR created:"),
    ("작업 브랜치", "Work branch"),
    ("작업 요청", "Work request"),
    ("작업 브랜치 확인 실패:", "Could not resolve work branch:"),
    ("AI 결과", "AI result"),
    ("확인할 모니터링 항목을 선택하세요.", "Choose a monitoring view."),
    ("이 봇의 프로젝트 컨텍스트를 찾을 수 없습니다.", "No project context is bound to this bot."),
    ("알 수 없는 프로젝트:", "Unknown project:"),
    ("알 수 없는 프로젝트", "Unknown project"),
    ("비활성화된 프로젝트:", "Disabled project:"),
    ("비활성화된 프로젝트", "Disabled project"),
    ("이 봇 프로젝트", "This bot project"),
    ("대화 기억 저장소가 설정되지 않았습니다.", "Conversation memory storage is not configured."),
    (
        "정리할 항목을 선택하세요. 실행 전 확인 버튼이 필요합니다.",
        "Choose what to clean up. A confirmation button is required before running.",
    ),
    ("기억 저장소가 설정되지 않았습니다.", "Memory storage is not configured."),
    ("현재 할 작업을 확인하세요.", "Confirm the work to run."),
    ("실행 여부를 선택하세요.", "Choose whether to run it."),
    ("인라인 Yes/No 버튼으로 확인한 뒤 작업이 접수됩니다.", "A job is accepted after confirmation with inline Yes/No buttons."),
    ("인라인 Yes/No 버튼으로 작업 실행 여부를 선택하세요.", "Choose whether to run with inline Yes/No buttons."),
    ("작업 요청을 취소했습니다.", "Cancelled the work request."),
    ("알 수 없는 clear 작업입니다.", "Unknown clear action."),
    ("봇에 연결된 프로젝트가 없거나 레지스트리에서 찾을 수 없습니다.", "No project is bound to this bot or found in the registry."),
    ("프로젝트가 비활성화되어 있습니다", "Project is disabled"),
    ("개 삭제", " deleted"),
    ("봇에 연결된 프로젝트가 없습니다.", "No project is bound to this bot."),
    ("이 채팅방의 대화 기억을 삭제했습니다.", "Deleted conversation memory for this chat."),
    ("진행 중 Job이 없습니다.", "No running job is available."),
    ("중단할 수 있는 진행 중 Job이 없습니다.", "No running job can be stopped."),
    ("중단할 Job을 선택하세요.", "Choose a job to stop."),
    ("작업 중단 기능을 사용할 수 없습니다.", "Job cancellation is not available."),
    ("작업 중단 요청 완료", "Stop requested"),
    ("Job을 찾을 수 없습니다", "Job not found"),
    ("작업을 중단할 수 없습니다", "Cannot stop job"),
    ("현재 상태", "current status"),
    ("확인 대기 작업을 처리할 수 없습니다.", "Could not process the pending confirmation."),
    ("확인 대기 작업이 없습니다.", "There is no pending confirmation."),
    ("알 수 없는 명령어입니다. /help 를 확인하세요.", "Unknown command. See /help."),
    ("변경 없음", "No changes"),
    ("(스테이징된 변경 없음 — push 생략)", "(nothing staged — push skipped)"),
    ("(no commit 옵션 — 커밋·push 생략)", "(no commit — commit/push skipped)"),
    ("(없음 — 변경 없어 브랜치 미생성)", "(none — no branch; no changes)"),
    ("미생성", "not created"),
    ("통합 브랜치(main 또는 master)를 찾을 수 없습니다. 저장소에 main 또는 master가 있어야 합니다.", "No integration branch (main or master). The repository needs main or master."),
    ("(detached HEAD — 브랜치 이름 없음)", "(detached HEAD — no branch name)"),
    ("(로컬 브랜치 없음)", "(no local branches)"),
    ("로컬 브랜치가 없습니다:", "No local branch:"),
    ("plan 모드로 실행할 작업 지시문을 보내주세요.", "Send the instruction to run in plan mode."),
    ("ask 모드로 실행할 질문을 보내주세요.", "Send the question to run in ask mode."),
    ("research 모드로 실행할 조사 질문을 보내주세요.", "Send the research question to run in research mode."),
    ("읽기 전용 · 커밋·push 없음", "read-only — no commit/push"),
    ("코드 수정·커밋·push 가능", "allows edit, commit, and push"),
    ("요청 브랜치", "Requested branch"),
    ("브랜치·커밋·push", "branch/commit/push"),
    ("메모리(SQLite)", "Memory (SQLite)"),
    ("역할별 행 수", "Rows by role"),
    ("로컬 브랜치", "Local branches"),
    ("원격 브랜치", "Remote branches"),
    ("Worktree 항목", "Worktree entries"),
    ("프로젝트:", "Project:"),
    ("DB 경로:", "DB path:"),
    ("이 채팅 저장 행 수:", "Rows for this chat:"),
    ("역할별 행 수:", "Rows by role:"),
    ("브랜치 모니터", "Branch monitor"),
    ("원격 이름:", "Remote name:"),
    ("현재 checkout:", "Current checkout:"),
    ("로컬 브랜치 수:", "Local branch count:"),
    ("원격 추적 브랜치 수:", "Tracked remote branches:"),
    ("[로컬]", "[Local]"),
    ("메시지 길이 제한으로 생략)", "truncated for message length)"),
    ("/monitor branch 실패:", "/monitor branch failed:"),
    ("/monitor worktrees 실패:", "/monitor worktrees failed:"),
    ("워크트리 모니터", "Worktree monitor"),
    ("관리 기준 디렉터리(worktree_base):", "Managed base (worktree_base):"),
    ("총 worktree 수:", "Total worktrees:"),
    ("managed 후보 수(remote-*·base·_rebase_ops):", "managed candidates (remote-*, base, _rebase_ops):"),
    ("[항목]", "[Entries]"),
    ("개 생략)", " omitted)"),
    ("코드 규모(추정)", "Code size (estimated)"),
    ("스캔한 코드 파일 수:", "Code files scanned:"),
    ("합계 줄 수(대략):", "Approx. total lines:"),
    ("건너뜀(바이너리/읽기 오류):", "Skipped (binary/read error):"),
    ("참고: 확장자 기준 텍스트 파일만 포함합니다. 대용량 저장소에서는 상한에 도달하면 일부만 집계됩니다.", "Note: only text-like extensions included; large repos may hit scan caps."),
    ("최근 Job 사용량", "Recent job usage"),
    ("이 채팅/프로젝트/모델로 완료되거나 실행된 Job 기록이 아직 없습니다.", "No completed/running jobs for this chat/project/model."),
    ("실제 세부 모델명과 토큰은 CLI 출력·로컬 로그에 남은 경우에만 표시됩니다.", "Model details/tokens appear only when present in CLI output or logs."),
    ("최근 Job:", "Latest job:"),
    ("확인한 Job 수:", "Jobs inspected:"),
    ("관측된 세부 모델:", "Observed model:"),
    ("CLI 기본값/설정에서 자동 선택됨 (로그에서 확인 불가)", "CLI default/auto-selected (not visible in logs)"),
    ("관측된 토큰 합계:", "Observed tokens (total):"),
    ("토큰 사용량 패턴을 로그에서 찾지 못했습니다.", "Could not find token usage patterns in logs."),
    ("실제 로컬 사용량/잔여량", "Local usage/quota snapshot"),
    ("로컬 CLI 사용량 로그를 찾지 못했습니다.", "Could not find local CLI usage logs."),
    ("출처:", "Source:"),
    ("관측 시각:", "Observed at:"),
    ("플랜/계정 유형:", "Plan/account type:"),
    ("관측된 토큰:", "Observed tokens:"),
    ("오늘 로컬 로그 기준 요청 수:", "Requests today (from local logs):"),
    ("잔여량:", "Remaining:"),
    ("5시간 한도", "5-hour limit"),
    ("주간 한도", "Weekly limit"),
    ("시간 한도", "-hour limit"),
    ("일 한도", "-day limit"),
    ("분 한도", "-minute limit"),
    ("명령을 찾을 수 없습니다.", "command not found."),
    ("설치 및 PATH를 확인하세요.", "Install it and verify PATH."),
    ("시간 초과.", " timed out."),
    ("auth status (--text):", "auth status (--text):"),
    ("auth status 실패", "auth status failed"),
    ("JSON이 아닌 출력입니다", "Output was not JSON"),
    ("처음 400자", "first 400 chars"),
    ("auth status (JSON 요약, 민감값 제외)", "auth status (JSON summary, sensitive values omitted)"),
    ("예상과 다른 JSON 형식입니다.", "Unexpected JSON shape."),
    ("CLI 버전:", "CLI version:"),
    ("버전 확인 실패", "version check failed"),
    ("설치: npm install -g @google/gemini-cli", "Install: npm install -g @google/gemini-cli"),
    ("...(생략)", "...(truncated)"),
    ("관리 UI는 로컬호스트에서만 사용할 수 있습니다.", "Admin UI is only available on localhost."),
    ("닫았습니다.", "Closed."),
)

_MESSAGE_CATALOG_KO: dict[str, str] = {
    "model.menu": "모델을 선택하세요.",
    "model.settings": "모델 설정\n\n- 현재 기본 모델: {selection}",
    "model.provider_selected": (
        "모델 제공자가 선택되었습니다.\n\n"
        "- 기본 모델: {provider}\n"
        "- 세부 모델을 선택하세요."
    ),
    "model.updated": "모델 설정이 변경되었습니다.\n\n- 기본 모델: {selection}",
    "model.unknown_specific": "알 수 없는 세부 모델입니다: {model_id}\n\n{usage}",
    "job.accepted": (
        "✅ 작업 접수 완료\n\n"
        "- Job ID: {job_id}{session_line}\n"
        "- 프로젝트: {project}\n"
        "- 모델: {model}{mode_line}"
    ),
    "job.mode_line": "\n- 모드: {mode}",
    "job.session_line": "\n- Session ID: {session_id}",
    "job.stop_button": "작업 중단",
    "job.run_plan_button": "계획 실행",
    "job.open_pr_button": "PR 올리기",
    "pr.no_candidates": "현재 프로젝트와 채팅의 성공 Job 브랜치가 `{remote}` 원격에 남아 있지 않습니다.",
    "pr.not_job_branch": "`{branch}`는 이 프로젝트와 채팅에서 성공한 Job 브랜치가 아닙니다.",
    "pr.remote_branch_missing": (
        "원격 브랜치 `{branch}`를 `{remote}`에서 찾을 수 없습니다. "
        "Job 완료 후 삭제되었을 수 있습니다."
    ),
    "pr.gh_missing": (
        "/pr 실패: GitHub CLI(gh)가 설치되어 있지 않거나 PATH에서 찾을 수 없습니다.\n\n"
        "Telegram에서 PR을 만들려면 다음 순서로 준비하세요.\n"
        "1. GitHub CLI 설치:\n"
        "   - macOS: `brew install gh`\n"
        "   - Windows: `winget install --id GitHub.cli`\n"
        "   - Ubuntu/Debian: `sudo apt install gh`\n"
        "2. GitHub 로그인: `gh auth login`\n"
        "3. Remote AI Coder 재시작: `remote-coder up`"
    ),
    "job.heartbeat": "{accepted}\n\n⏳ 실행 중 ({minutes}분 경과)",
    "job.cancelled": "{mode_prefix}⛔ 작업 중단됨\n\n- Job ID: {job_id}{session_line}\n- 프로젝트: {project}",
    "job.readonly_completed": (
        "[{mode}] 응답 완료\n\n"
        "- Job ID: {job_id}{session_line}\n"
        "- 프로젝트: {project}\n"
        "- 사용 모델: {model}\n"
        "- 토큰 사용량: {token_usage}{response_block}"
    ),
    "job.response_block": "\n\nAI 응답:\n{summary}",
    "job.no_changes": "변경 없음",
    "job.branch_none_no_changes": "(없음 - 변경 없어 브랜치 미생성)",
    "job.no_commit_skipped": "(no commit - 커밋/push 생략)",
    "job.nothing_staged_skipped": "(스테이징된 변경 없음 - push 생략)",
    "common.unavailable": "확인 불가",
    "job.completed": (
        "✅ 작업 완료\n\n"
        "- Job ID: {job_id}{session_line}\n"
        "- 프로젝트: {project}\n"
        "- 브랜치: {branch}\n"
        "- 커밋: {commit}\n"
        "- 변경 파일: {changed}\n"
        "- 사용 모델: {model}\n"
        "- 토큰 사용량: {token_usage}{response_block}"
    ),
    "job.failed": (
        "{mode_prefix}❌ 작업 실패\n\n"
        "- Job ID: {job_id}{session_line}\n"
        "- 프로젝트: {project}\n"
        "- 오류: {error}{details}{failure_block}"
    ),
    "job.failure_detail_stage": "\n- 실패 단계: {stage}",
    "job.failure_detail_log_path": "\n- 로그 경로: {log_path}",
    "job.failure_block": "\n\n실패 출력 요약:\n{summary}",
    "server.started": "✅ Remote AI Coder 서버가 시작되었습니다.\n{body}",
    "server.shutdown": "🔴 Remote AI Coder 서버 연결이 종료되었습니다.",
}


_TEXT_REPLACEMENTS_RAW: tuple[tuple[str, str], ...] = tuple(
    (english, korean) for korean, english in _TEXT_REPLACEMENTS_KO_TO_EN_RAW
    if english not in {".", "- Mode", "Model provider selected."}
) + (
    ("- Mode:", "- 모드:"),
    ("Model provider selected.", "모델 제공자가 선택되었습니다."),
)

_TEXT_REPLACEMENTS = tuple(sorted(set(_TEXT_REPLACEMENTS_RAW), key=lambda p: len(p[0]), reverse=True))
_EXACT_TEXT_REPLACEMENTS = dict(_TEXT_REPLACEMENTS)


_REGEX_TRANSLATIONS = (
    re.compile(r"Fetched updates from remote ([^.]+)\."),
    re.compile(r" Updated current branch \(([^)]+)\)\."),
    re.compile(r" Fast-forward updated (\d+) additional local branch\(es\)\."),
    re.compile(
        r"Rebase complete: rebased `([^`]+)` onto `([^`]+)/([^`]+)`, "
        r"fast-forward merged into `([^`]+)`, pushed to `([^`]+)`\."
    ),
    re.compile(r"git fetch (\S+) failed:"),
    re.compile(r"git pull (\S+) (\S+) failed \(possible conflict\):"),
    re.compile(r"gh pr create failed:"),
    re.compile(r"\(no remote branches on ([^\n()]+)\)"),
    re.compile(r"\[([^\]\n]+) remote\]"),
    re.compile(r"(\d+)m (\d+)s"),
    re.compile(r"(\d+)s"),
    re.compile(r"Changed files \((\d+) files\)"),
    re.compile(r"- \.\.\. and (\d+) more"),
    re.compile(r"\n\.\.\.\(omitted (\d+) entries\)"),
)


def _regex_patch_korean(text: str) -> str:
    replacements = (
        lambda m: f"원격({m.group(1)})에서 모든 정보를 가져왔습니다.",
        lambda m: f" 현재 브랜치({m.group(1)})를 업데이트했습니다.",
        lambda m: f" 추가로 {m.group(1)}개의 로컬 브랜치를 fast-forward 업데이트했습니다.",
        lambda m: (
            f"rebase 완료: 브랜치 `{m.group(1)}`를 `{m.group(2)}/{m.group(3)}` 기준으로 rebase 후 "
            f"`{m.group(4)}`에 fast-forward 병합하고 `{m.group(5)}`에 push했습니다."
        ),
        lambda m: f"git fetch {m.group(1)} 실패:",
        lambda m: f"git pull {m.group(1)} {m.group(2)} 실패 (충돌 가능성):",
        lambda m: "gh pr create 실패:",
        lambda m: f"({m.group(1)} 원격 브랜치 없음)",
        lambda m: f"[{m.group(1)} remote]",
        lambda m: f"{m.group(1)}분 {m.group(2)}초",
        lambda m: f"{m.group(1)}초",
        lambda m: f"변경 파일 ({m.group(1)}개)",
        lambda m: f"- ... 외 {m.group(1)}개",
        lambda m: f"\n...(외 {m.group(1)}개 생략)",
    )
    result = text
    for rx, repl in zip(_REGEX_TRANSLATIONS, replacements, strict=True):
        result = rx.sub(repl, result)
    return result


_BUTTON_LABELS = {
    "Help": "도움말",
    "Modes": "모드별 안내",
    "Monitor": "모니터링",
    "Clean": "정리",
    "Manage": "관리",
    "Reports": "리포트",
    "Branch": "브랜치 확인",
    "Rebase": "리베이스",
    "Open PR": "PR 올리기",
    "View full log": "전체 로그 보기",
    "Stop": "중단",
    "Status": "상태",
    "Model": "모델",
    "Reset": "초기화",
    "Back": "뒤로",
    "← Back": "← 뒤로",
    "‹ Back": "‹ 뒤로",
    "✖ Close": "✖ 닫기",
    "Yes": "네",
    "No": "아니오",
    "Stop job": "작업 중단",
    "AGENTS mode": "AGENTS 모드",
    "PLAN mode": "PLAN 모드",
    "ASK mode": "ASK 모드",
    "RESEARCH mode": "RESEARCH 모드",
}


_LABELED_LIST_LABELS = {
    "Project": "프로젝트",
    "chat_id": "채팅 ID",
    "DB path": "DB 경로",
    "DB exists": "DB 존재",
    "DB size": "DB 크기",
    "Rows for this chat": "이 채팅 저장 행 수",
    "Sessions": "세션 수",
    "root": "루트",
    "Remote": "원격 이름",
    "Current checkout": "현재 checkout",
    "Local branches": "로컬 브랜치 수",
    "Remote-tracking branches": "원격 추적 브랜치 수",
    "Managed base directory": "관리 기준 디렉터리",
    "Total worktrees": "총 worktree 수",
    "Detached worktrees": "detached worktree 수",
    "Managed candidates": "managed 후보 수",
}
_LABELED_LIST_PATTERN = "|".join(
    re.escape(label) for label in sorted(_LABELED_LIST_LABELS, key=len, reverse=True)
)


def _translate_labeled_list_line(match: re.Match[str]) -> str:
    label = match.group("label")
    translated = _LABELED_LIST_LABELS.get(label)
    if translated is None:
        return match.group(0)
    return f"- {translated}: {match.group('value')}"


_LINE_TRANSLATIONS = (
    (
        re.compile(rf"^- (?P<label>{_LABELED_LIST_PATTERN}): (?P<value>.*)$"),
        _translate_labeled_list_line,
    ),
    (re.compile(r"^- Choose a specific model\.$"), lambda m: "- 세부 모델을 선택하세요."),
    (
        re.compile(r"^- Mode: agent \(allows edit, commit, and push\)$"),
        lambda m: "- 모드: agent (코드 수정·커밋·push 가능)",
    ),
    (
        re.compile(r"^- Mode: ([^(].*)$"),
        lambda m: f"- 모드: {m.group(1)}",
    ),
    (
        re.compile(r"^- 5-hour limit: remaining (.*)$"),
        lambda m: f"- 5시간 한도: 잔여 {m.group(1)}",
    ),
    (
        re.compile(r"^- Weekly limit: remaining (.*)$"),
        lambda m: f"- 주간 한도: 잔여 {m.group(1)}",
    ),
    (re.compile(r"^- Project: (.*)$"), lambda m: f"- 프로젝트: {m.group(1)}"),
    (re.compile(r"^- Model: (.*)$"), lambda m: f"- 모델: {m.group(1)}"),
    (re.compile(r"^- Model used: (.*)$"), lambda m: f"- 사용 모델: {m.group(1)}"),
    (re.compile(r"^- Requested model: (.*)$"), lambda m: f"- 요청 모델: {m.group(1)}"),
    (re.compile(r"^- Default model: (.*)$"), lambda m: f"- 기본 모델: {m.group(1)}"),
    (re.compile(r"^- Current default model: (.*)$"), lambda m: f"- 현재 기본 모델: {m.group(1)}"),
    (re.compile(r"^- Token usage: (.*)$"), lambda m: f"- 토큰 사용량: {m.group(1)}"),
    (re.compile(r"^- Branch: (.*)$"), lambda m: f"- 브랜치: {m.group(1)}"),
    (re.compile(r"^- Commit: (.*)$"), lambda m: f"- 커밋: {m.group(1)}"),
    (re.compile(r"^- Changed files: (.*)$"), lambda m: f"- 변경 파일: {m.group(1)}"),
    (re.compile(r"^- Status: (.*)$"), lambda m: f"- 상태: {m.group(1)}"),
    (re.compile(r"^- Instruction: (.*)$"), lambda m: f"- 지시: {m.group(1)}"),
    (re.compile(r"^- Error: (.*)$"), lambda m: f"- 오류: {m.group(1)}"),
    (re.compile(r"^- Error stage: (.*)$"), lambda m: f"- 오류 단계: {m.group(1)}"),
    (re.compile(r"^- Failure stage: (.*)$"), lambda m: f"- 실패 단계: {m.group(1)}"),
    (re.compile(r"^- Log path: (.*)$"), lambda m: f"- 로그 경로: {m.group(1)}"),
    (re.compile(r"^- Started: (.*)$"), lambda m: f"- 시작: {m.group(1)}"),
    (re.compile(r"^- Created: (.*)$"), lambda m: f"- 생성: {m.group(1)}"),
    (re.compile(r"^Project: (.*)$"), lambda m: f"프로젝트: {m.group(1)}"),
    (re.compile(r"^Current branch: (.*)$"), lambda m: f"현재 브랜치: {m.group(1)}"),
    (re.compile(r"^Default model: (.*)$"), lambda m: f"기본 모델: {m.group(1)}"),
    (re.compile(r"^Total entries: (.*)$"), lambda m: f"총 기록: {m.group(1)}"),
    (re.compile(r"^User requests: (.*)$"), lambda m: f"사용자 요청: {m.group(1)}"),
    (re.compile(r"^Jobs accepted: (.*)$"), lambda m: f"Job 접수: {m.group(1)}"),
    (re.compile(r"^Job results: (.*)$"), lambda m: f"Job 결과: {m.group(1)}"),
    (re.compile(r"^Latest user request: (.*)$"), lambda m: f"최근 사용자 요청: {m.group(1)}"),
    (re.compile(r"^Latest job result: (.*)$"), lambda m: f"최근 Job 결과: {m.group(1)}"),
)


def _translate_known_lines(text: str) -> str:
    rendered: list[str] = []
    for raw_line in text.splitlines(keepends=True):
        newline = ""
        line = raw_line
        if raw_line.endswith("\r\n"):
            line = raw_line[:-2]
            newline = "\r\n"
        elif raw_line.endswith("\n"):
            line = raw_line[:-1]
            newline = "\n"
        translated = _EXACT_TEXT_REPLACEMENTS.get(line)
        if translated is None and line != line.strip():
            stripped_translation = _EXACT_TEXT_REPLACEMENTS.get(line.strip())
            if stripped_translation is not None:
                leading = line[: len(line) - len(line.lstrip())]
                trailing = line[len(line.rstrip()) :]
                translated = leading + stripped_translation + trailing
        if translated is None:
            for rx, repl in _LINE_TRANSLATIONS:
                match = rx.match(line)
                if match is not None:
                    translated = repl(match)
                    break
        rendered.append((translated if translated is not None else line) + newline)
    return "".join(rendered)


def translate_text(text: str, language: UiLanguage) -> str:
    if language is UiLanguage.ENGLISH:
        return str(text)
    if isinstance(text, UiMessage):
        return text.render(language)
    translated = _regex_patch_korean(text)
    return _translate_known_lines(translated)


def translate_button_label(label: str, language: UiLanguage) -> str:
    if language is UiLanguage.ENGLISH:
        return str(label)
    if isinstance(label, UiMessage):
        return label.render(language)
    return _BUTTON_LABELS.get(label, label.replace(" mode", " 모드"))
