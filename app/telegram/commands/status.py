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
    description = "Show recent jobs and job status"

    def execute(self, message: TelegramMessage, ctx: CommandContext) -> str:
        tokens = message.text.strip().split()
        project_name = effective_project_name_for_chat(ctx, message.chat_id)
        if len(tokens) == 1:
            if not project_name:
                return (
                    "No project is registered. "
                    "Register a project at http://127.0.0.1:8000/projects."
                )
            limit = self._job_limit(ctx)
            jobs = ctx.job_store.list_recent_for_project_chat(
                project_name, message.chat_id, limit
            )
            if not jobs:
                return "No jobs are available."
            return "Choose a job to inspect."
        if len(tokens) != 2:
            return format_usage("/status <job_id>")
        job = ctx.job_store.get(tokens[1])
        if not job:
            return "Job ID not found."
        if project_name and job.request.project != project_name:
            return "Job ID not found."
        return self._format_job_detail(job)

    @staticmethod
    def _fmt_time(dt: datetime) -> str:
        return dt.astimezone().strftime("%H:%M:%S")

    @staticmethod
    def _duration_str(seconds: int) -> str:
        mins, secs = divmod(seconds, 60)
        return f"{mins}m {secs}s" if mins > 0 else f"{secs}s"

    @classmethod
    def _format_job_detail(cls, job: Job) -> str:
        lines: list[str] = []
        emoji = _STATUS_EMOJI.get(job.status.value, "")
        lines.append(f"Job {job.id}")
        lines.append("")
        lines.append(f"- Status: {job.status.value} {emoji}")
        lines.append(f"- Project: {job.request.project}")
        requested_model = format_model_selection(job.request.model, job.request.model_id)
        lines.append(f"- Requested model: {requested_model}")
        lines.append(f"- Model used: {job.runner_actual_model or requested_model}")
        lines.append(f"- Token usage: {format_token_usage(job.runner_token_usage) or 'unavailable'}")

        instr = job.request.instruction.strip().replace("\n", " ")
        if len(instr) > 80:
            instr = instr[:80].rstrip() + "..."
        lines.append(f"- Instruction: {instr}")

        now = datetime.now(UTC)
        started = job.started_at
        finished = job.finished_at
        if started:
            if finished:
                elapsed = int((finished - started).total_seconds())
                lines.append(
                    f"- Started: {cls._fmt_time(started)} → Finished: {cls._fmt_time(finished)}"
                    f" (duration: {cls._duration_str(elapsed)})"
                )
            else:
                elapsed = int((now - started).total_seconds())
                lines.append(
                    f"- Started: {cls._fmt_time(started)} (elapsed: {cls._duration_str(elapsed)})"
                )
        else:
            lines.append(f"- Created: {cls._fmt_time(job.created_at)}")

        if job.status.value == "succeeded":
            if job.branch:
                lines.append(f"- Branch: {job.branch}")
            if job.commit_hash:
                lines.append(f"- Commit: {job.commit_hash[:8]}")
            if job.changed_files:
                lines.append("")
                lines.append(f"Changed files ({len(job.changed_files)} files)")
                for f in job.changed_files[:_MAX_CHANGED_FILES]:
                    lines.append(f"- {f}")
                if len(job.changed_files) > _MAX_CHANGED_FILES:
                    lines.append(f"- ... and {len(job.changed_files) - _MAX_CHANGED_FILES} more")
            else:
                lines.append("- Changed files: none (no-op)")
            if job.runner_stdout_summary:
                lines.append("")
                lines.append("[AI output summary]")
                summary = job.runner_stdout_summary
                if len(summary) > _STDOUT_TAIL:
                    summary = "...(truncated)\n" + summary[-_STDOUT_TAIL:]
                lines.append(summary)

        elif job.status.value == "failed":
            if job.error_stage:
                lines.append(f"- Error stage: {job.error_stage}")
            if job.error:
                lines.append(f"- Error: {job.error[:300]}")
            if job.runner_stderr_summary:
                lines.append("")
                lines.append("[stderr]")
                lines.append(job.runner_stderr_summary[-_STDERR_TAIL:])

        elif job.status.value == "running" and job.runner_stdout_summary:
            lines.append("")
            lines.append("[Current output]")
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
    description = "Show this chat's conversation memory summary"

    _DEFAULT_RECENT_LIMIT = 5
    _MAX_RECENT_LIMIT = 10

    def execute(self, message: TelegramMessage, ctx: CommandContext) -> str:
        tokens = message.text.strip().split()
        if len(tokens) > 2:
            return "Usage: /reports or /reports <recent_limit>"

        recent_limit = self._DEFAULT_RECENT_LIMIT
        if len(tokens) == 2:
            try:
                recent_limit = int(tokens[1])
            except ValueError:
                return "Usage: /reports or /reports <recent_limit>"
            if recent_limit < 1 or recent_limit > self._MAX_RECENT_LIMIT:
                return f"recent_limit must be a number between 1 and {self._MAX_RECENT_LIMIT}."

        if ctx.conversation_store is None:
            return "Conversation memory storage is not configured."

        project_name = effective_project_name_for_chat(ctx, message.chat_id)
        if not project_name:
            return (
                "No project is registered. "
                "Register a project at http://127.0.0.1:8000/projects."
            )

        entry = ctx.project_registry.get(project_name)
        if not entry:
            return f"Unknown project: {project_name}"
        if not entry.enabled:
            return f"Disabled project: {project_name}"

        report = ctx.conversation_store.generate_report(project_name, message.chat_id, recent_limit)
        if report is None:
            return f"No conversation memory is stored. (project={project_name})"

        lines = [
            "Memory report",
            f"Project: {project_name}",
            f"Total entries: {report.total_entries}",
            f"User requests: {report.count_for('user')}",
            f"Jobs accepted: {report.count_for('job_accepted')}",
            f"Job results: {report.count_for('job_result')}",
        ]
        if report.latest_user_text:
            lines.append(f"Latest user request: {self._truncate(report.latest_user_text)}")
        if report.latest_job_result:
            job_label = report.latest_job_id or "(no job_id)"
            lines.append(f"Latest job result: {job_label} {self._truncate(report.latest_job_result)}")
        if report.recent_entries:
            lines.append("")
            lines.append("Recent memory")
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
