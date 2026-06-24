from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.ai.model_catalog import format_model_selection
from app.ai.usage import format_token_usage
from app.jobs.result_writer import extract_stdout_from_log
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
    with_nav_row,
)

if TYPE_CHECKING:
    from app.telegram.conversation.models import ConversationReport

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
_RECENT_JOB_LIMIT = 10


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
        lines = cls._header_lines(job)
        lines += cls._timing_lines(job, datetime.now(UTC))
        if job.status.value == "succeeded":
            lines += cls._succeeded_lines(job)
        elif job.status.value == "failed":
            lines += cls._failed_lines(job)
        elif job.status.value == "running":
            lines += cls._running_lines(job)
        return "\n".join(lines)

    @staticmethod
    def _header_lines(job: Job) -> list[str]:
        emoji = _STATUS_EMOJI.get(job.status.value, "")
        lines: list[str] = [f"Job {job.id}", ""]
        if job.request.session_id:
            lines.append(f"- Session ID: {job.request.session_id}")
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
        return lines

    @classmethod
    def _timing_lines(cls, job: Job, now: datetime) -> list[str]:
        started = job.started_at
        finished = job.finished_at
        if not started:
            return [f"- Created: {cls._fmt_time(job.created_at)}"]
        if finished:
            elapsed = int((finished - started).total_seconds())
            return [
                f"- Started: {cls._fmt_time(started)} → Finished: {cls._fmt_time(finished)}"
                f" (duration: {cls._duration_str(elapsed)})"
            ]
        elapsed = int((now - started).total_seconds())
        return [f"- Started: {cls._fmt_time(started)} (elapsed: {cls._duration_str(elapsed)})"]

    @staticmethod
    def _succeeded_lines(job: Job) -> list[str]:
        lines: list[str] = []
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
        return lines

    @staticmethod
    def _failed_lines(job: Job) -> list[str]:
        lines: list[str] = []
        if job.error_stage:
            lines.append(f"- Error stage: {job.error_stage}")
        if job.error:
            lines.append(f"- Error: {job.error[:300]}")
        if job.runner_stderr_summary:
            lines.append("")
            lines.append("[stderr]")
            lines.append(job.runner_stderr_summary[-_STDERR_TAIL:])
        return lines

    @staticmethod
    def _running_lines(job: Job) -> list[str]:
        if not job.runner_stdout_summary:
            return []
        return ["", "[Current output]", job.runner_stdout_summary[-_STDOUT_TAIL:]]

    @staticmethod
    def _job_limit(ctx: CommandContext) -> int:
        return _RECENT_JOB_LIMIT

    def get_inline_buttons(
        self,
        message: TelegramMessage | None = None,
        ctx: CommandContext | None = None,
    ) -> list[list[InlineButton]] | None:
        if message is None or ctx is None:
            return None
        tokens = message.text.strip().split()
        project_name = effective_project_name_for_chat(ctx, message.chat_id)
        if len(tokens) == 2:
            return self._detail_buttons(tokens[1], project_name, ctx)
        if len(tokens) != 1:
            return None
        if not project_name:
            return None
        limit = self._job_limit(ctx)
        jobs = ctx.job_store.list_recent_for_project_chat(
            project_name, message.chat_id, limit
        )
        if not jobs:
            return None
        rows = _button_rows(
            [InlineButton(_job_button_label(job), f"/status {job.id}") for job in jobs],
            per_row=1,
        )
        return with_nav_row(rows)

    @staticmethod
    def _detail_buttons(
        job_id: str,
        project_name: str | None,
        ctx: CommandContext,
    ) -> list[list[InlineButton]]:
        job = ctx.job_store.get(job_id)
        if job is None or (project_name and job.request.project != project_name):
            return with_nav_row(None, back_to="/status")
        rows: list[list[InlineButton]] = []
        status = job.status.value
        if status in ("running", "queued"):
            rows.append([InlineButton("Stop", f"/stop {job.id}", style="danger")])
        elif status == "succeeded" and job.branch:
            actions: list[InlineButton] = []
            if job.commit_hash:
                actions.append(InlineButton("Open PR", f"/pr {job.branch}", style="primary"))
            actions.append(InlineButton("Rebase", f"/rebase {job.branch}"))
            rows.append(actions)
        if job.log_path is not None:
            rows.append([InlineButton("View full log", f"/log {job.id}")])
        return with_nav_row(rows, back_to="/status")


class LogCommand(TelegramCommand):
    name = "/log"
    description = "Show job AI output logs"

    def execute(self, message: TelegramMessage, ctx: CommandContext) -> str:
        tokens = message.text.strip().split()
        project_name = effective_project_name_for_chat(ctx, message.chat_id)
        if len(tokens) == 1:
            if not project_name:
                return (
                    "No project is registered. "
                    "Register a project at http://127.0.0.1:8000/projects."
                )
            jobs = ctx.job_store.list_recent_for_project_chat(
                project_name, message.chat_id, _RECENT_JOB_LIMIT
            )
            if not jobs:
                return "No jobs are available."
            return "Choose a job log to view."
        if len(tokens) != 2:
            return format_usage("/log <job_id>")
        job = ctx.job_store.get(tokens[1])
        if not job:
            return "Job ID not found."
        if project_name and job.request.project != project_name:
            return "Job ID not found."
        body = self._resolve_body(job)
        if body is None:
            return "No AI output is available for this job."
        title = "Current AI output" if job.status.value == "running" else "Full AI output"
        return f"📄 {title} — Job {job.id}\n\n{body}"

    def get_inline_buttons(
        self,
        message: TelegramMessage | None = None,
        ctx: CommandContext | None = None,
    ) -> list[list[InlineButton]] | None:
        if message is None or ctx is None:
            return None
        tokens = message.text.strip().split()
        if len(tokens) != 1:
            return None
        project_name = effective_project_name_for_chat(ctx, message.chat_id)
        if not project_name:
            return None
        jobs = ctx.job_store.list_recent_for_project_chat(
            project_name, message.chat_id, _RECENT_JOB_LIMIT
        )
        if not jobs:
            return None
        rows = _button_rows(
            [InlineButton(_job_button_label(job), f"/log {job.id}") for job in jobs],
            per_row=1,
        )
        return with_nav_row(rows)

    @staticmethod
    def _resolve_body(job: Job) -> str | None:
        if job.log_path is not None:
            stdout = extract_stdout_from_log(job.log_path)
            if stdout:
                return stdout
        if job.runner_stdout_summary:
            return job.runner_stdout_summary
        return None


class ReportsCommand(TelegramCommand):
    name = "/reports"
    description = "Show this chat's conversation memory summary"

    _DEFAULT_RECENT_LIMIT = 5
    _MAX_RECENT_LIMIT = 10

    def execute(self, message: TelegramMessage, ctx: CommandContext) -> str:
        resolved = self._resolve_report_target(message, ctx)
        if isinstance(resolved, str):
            return resolved
        project_name, report = resolved
        return "\n".join(self._render_report(project_name, report, ctx))

    def _resolve_report_target(
        self, message: TelegramMessage, ctx: CommandContext
    ) -> tuple[str, ConversationReport] | str:
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
        return project_name, report

    def _render_report(
        self, project_name: str, report: ConversationReport, ctx: CommandContext
    ) -> list[str]:
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
            if report.latest_job_id:
                latest_job = ctx.job_store.get(report.latest_job_id)
                if latest_job is not None and latest_job.request.session_id:
                    lines.append(f"Session ID: {latest_job.request.session_id}")
        if report.recent_entries:
            lines.append("")
            lines.append("Recent memory")
            for item in report.recent_entries:
                label = item.role
                if item.job_id:
                    label = f"{label}:{item.job_id}"
                lines.append(f"- [{label}] {self._truncate(item.text, limit=90)}")
        return lines

    @staticmethod
    def _truncate(text: str, limit: int = 120) -> str:
        normalized = text.strip().replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
        if len(normalized) <= limit:
            return normalized
        return normalized[:limit].rstrip() + "..."
