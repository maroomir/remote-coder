from __future__ import annotations

from datetime import UTC, datetime

from app.ai.model_catalog import format_model_selection
from app.ai.usage import format_token_usage
from app.jobs.schemas import Job
from app.telegram.commands.base import (
    CommandContext,
    InlineButton,
    TelegramCommand,
    TelegramMessage,
    _button_rows,
    _job_button_label,
    effective_project_name_for_chat,
    format_usage,
)

_STATUS_EMOJI: dict[str, str] = {
    "queued": "⏳",
    "running": "🔄",
    "succeeded": "✅",
    "failed": "❌",
    "cancelled": "⛔",
}
_STDOUT_TAIL = 1500
_STDERR_TAIL = 800
_MAX_CHANGED_FILES = 10


class StatusCommand(TelegramCommand):
    name = "/status"
    description = "최근 Job 목록과 작업 상태를 조회합니다"

    def execute(self, message: TelegramMessage, ctx: CommandContext) -> str:
        tokens = message.text.strip().split()
        project_name = effective_project_name_for_chat(ctx, message.chat_id)
        if len(tokens) == 1:
            if not project_name:
                return (
                    "등록된 프로젝트가 없습니다. "
                    "브라우저에서 http://127.0.0.1:8000/projects 로 프로젝트를 등록하세요."
                )
            limit = self._job_limit(ctx)
            jobs = ctx.job_store.list_recent_for_project_chat(
                project_name, message.chat_id, limit
            )
            if not jobs:
                return "조회할 수 있는 Job이 없습니다."
            return "조회할 Job을 선택하세요."
        if len(tokens) != 2:
            return format_usage("/status <job_id>")
        job = ctx.job_store.get(tokens[1])
        if not job:
            return "해당 Job ID를 찾을 수 없습니다."
        if project_name and job.request.project != project_name:
            return "해당 Job ID를 찾을 수 없습니다."
        return self._format_job_detail(job)

    @staticmethod
    def _fmt_time(dt: datetime) -> str:
        return dt.astimezone().strftime("%H:%M:%S")

    @staticmethod
    def _duration_str(seconds: int) -> str:
        mins, secs = divmod(seconds, 60)
        return f"{mins}분 {secs}초" if mins > 0 else f"{secs}초"

    @classmethod
    def _format_job_detail(cls, job: Job) -> str:
        lines: list[str] = []
        emoji = _STATUS_EMOJI.get(job.status.value, "")
        lines.append(f"Job {job.id}")
        lines.append("")
        lines.append(f"- 상태: {job.status.value} {emoji}")
        lines.append(f"- 프로젝트: {job.request.project}")
        requested_model = format_model_selection(job.request.model, job.request.model_id)
        lines.append(f"- 요청 모델: {requested_model}")
        lines.append(f"- 사용 모델: {job.runner_actual_model or requested_model}")
        lines.append(f"- 토큰 사용량: {format_token_usage(job.runner_token_usage) or '확인 불가'}")

        instr = job.request.instruction.strip().replace("\n", " ")
        if len(instr) > 80:
            instr = instr[:80].rstrip() + "..."
        lines.append(f"- 지시: {instr}")

        now = datetime.now(UTC)
        started = job.started_at
        finished = job.finished_at
        if started:
            if finished:
                elapsed = int((finished - started).total_seconds())
                lines.append(
                    f"- 시작: {cls._fmt_time(started)} → 완료: {cls._fmt_time(finished)}"
                    f" (소요: {cls._duration_str(elapsed)})"
                )
            else:
                elapsed = int((now - started).total_seconds())
                lines.append(
                    f"- 시작: {cls._fmt_time(started)} (경과: {cls._duration_str(elapsed)})"
                )
        else:
            lines.append(f"- 생성: {cls._fmt_time(job.created_at)}")

        if job.status.value == "succeeded":
            if job.branch:
                lines.append(f"- 브랜치: {job.branch}")
            if job.commit_hash:
                lines.append(f"- 커밋: {job.commit_hash[:8]}")
            if job.changed_files:
                lines.append("")
                lines.append(f"변경 파일 ({len(job.changed_files)}개)")
                for f in job.changed_files[:_MAX_CHANGED_FILES]:
                    lines.append(f"- {f}")
                if len(job.changed_files) > _MAX_CHANGED_FILES:
                    lines.append(f"- ... 외 {len(job.changed_files) - _MAX_CHANGED_FILES}개")
            else:
                lines.append("- 변경 파일: 없음 (no-op)")
            if job.runner_stdout_summary:
                lines.append("")
                lines.append("[AI 출력 요약]")
                summary = job.runner_stdout_summary
                if len(summary) > _STDOUT_TAIL:
                    summary = "...(앞부분 생략)\n" + summary[-_STDOUT_TAIL:]
                lines.append(summary)

        elif job.status.value == "failed":
            if job.error_stage:
                lines.append(f"- 오류 단계: {job.error_stage}")
            if job.error:
                lines.append(f"- 오류: {job.error[:300]}")
            if job.runner_stderr_summary:
                lines.append("")
                lines.append("[stderr]")
                lines.append(job.runner_stderr_summary[-_STDERR_TAIL:])

        elif job.status.value == "running" and job.runner_stdout_summary:
            lines.append("")
            lines.append("[현재 출력]")
            lines.append(job.runner_stdout_summary[-_STDOUT_TAIL:])

        return "\n".join(lines)

    @staticmethod
    def _job_limit(ctx: CommandContext) -> int:
        if ctx.advanced_settings_store is None:
            return 10
        return ctx.advanced_settings_store.get().status_recent_job_limit

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
        limit = self._job_limit(ctx)
        jobs = ctx.job_store.list_recent_for_project_chat(
            project_name, message.chat_id, limit
        )
        if not jobs:
            return None
        return _button_rows(
            [InlineButton(_job_button_label(job), f"/status {job.id}") for job in jobs],
            per_row=1,
        )


class ReportsCommand(TelegramCommand):
    name = "/reports"
    description = "현재 채팅의 대화 기억 요약을 조회합니다"

    _DEFAULT_RECENT_LIMIT = 5
    _MAX_RECENT_LIMIT = 10

    def execute(self, message: TelegramMessage, ctx: CommandContext) -> str:
        tokens = message.text.strip().split()
        if len(tokens) > 2:
            return "사용법: /reports 또는 /reports <recent_limit>"

        recent_limit = self._DEFAULT_RECENT_LIMIT
        if len(tokens) == 2:
            try:
                recent_limit = int(tokens[1])
            except ValueError:
                return "사용법: /reports 또는 /reports <recent_limit>"
            if recent_limit < 1 or recent_limit > self._MAX_RECENT_LIMIT:
                return f"recent_limit 은 1~{self._MAX_RECENT_LIMIT} 사이의 숫자여야 합니다."

        if ctx.conversation_store is None:
            return "대화 기억 저장소가 설정되지 않았습니다."

        project_name = effective_project_name_for_chat(ctx, message.chat_id)
        if not project_name:
            return (
                "등록된 프로젝트가 없습니다. "
                "브라우저에서 http://127.0.0.1:8000/projects 로 프로젝트를 등록하세요."
            )

        entry = ctx.project_registry.get(project_name)
        if not entry:
            return f"알 수 없는 프로젝트: {project_name}"
        if not entry.enabled:
            return f"비활성화된 프로젝트: {project_name}"

        report = ctx.conversation_store.generate_report(project_name, message.chat_id, recent_limit)
        if report is None:
            return f"기억된 대화 기록이 없습니다. (project={project_name})"

        lines = [
            "기억 리포트",
            f"프로젝트: {project_name}",
            f"총 기록: {report.total_entries}개",
            f"사용자 요청: {report.count_for('user')}개",
            f"Job 접수: {report.count_for('job_accepted')}개",
            f"Job 결과: {report.count_for('job_result')}개",
        ]
        if report.latest_user_text:
            lines.append(f"최근 사용자 요청: {self._truncate(report.latest_user_text)}")
        if report.latest_job_result:
            job_label = report.latest_job_id or "(job_id 없음)"
            lines.append(f"최근 Job 결과: {job_label} {self._truncate(report.latest_job_result)}")
        if report.recent_entries:
            lines.append("")
            lines.append("최근 기억")
            for item in report.recent_entries:
                label = item.role
                if item.job_id:
                    label = f"{label}:{item.job_id}"
                lines.append(f"- [{label}] {self._truncate(item.text, limit=90)}")
        return "\n".join(lines)

    @staticmethod
    def _truncate(text: str, limit: int = 120) -> str:
        normalized = text.strip().replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
        if len(normalized) <= limit:
            return normalized
        return normalized[:limit].rstrip() + "..."
