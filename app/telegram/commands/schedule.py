from __future__ import annotations

import re
from uuid import uuid4

from app.jobs.schedule import MIN_INTERVAL_SECONDS, ScheduleRecord
from app.jobs.schemas import JobMode, is_read_only_job_mode
from app.telegram.commands.base import (
    CommandContext,
    ConfirmableCommand,
    InlineButton,
    TelegramMessage,
    _button_rows,
    effective_model_for_chat,
    effective_project_name_for_chat,
    format_usage,
)
from app.telegram.confirmations import PendingConfirmation

SCHEDULE_DELETE_PREFIX = "__schedule_delete__"

_INTERVAL_PATTERN = re.compile(r"^(\d+)([mhd])$")
_INTERVAL_UNIT_SECONDS = {"m": 60, "h": 3600, "d": 86400}
# Upper bound so an absurd interval (e.g. 999999999d) cannot create a schedule that silently
# never fires; a year is far beyond any realistic periodic-check cadence.
_MAX_INTERVAL_SECONDS = 365 * 86400

# Only read-only modes may be scheduled; write modes (agent, fix) are never unattended.
_SCHEDULABLE_MODES = {"research": JobMode.RESEARCH, "ask": JobMode.ASK, "plan": JobMode.PLAN}


def _parse_interval_seconds(token: str) -> int | None:
    match = _INTERVAL_PATTERN.match(token.strip().lower())
    if not match:
        return None
    amount = int(match.group(1))
    seconds = amount * _INTERVAL_UNIT_SECONDS[match.group(2)]
    if seconds < MIN_INTERVAL_SECONDS or seconds > _MAX_INTERVAL_SECONDS:
        return None
    return seconds


def _format_interval(seconds: int) -> str:
    if seconds % 86400 == 0:
        return f"{seconds // 86400}d"
    if seconds % 3600 == 0:
        return f"{seconds // 3600}h"
    return f"{seconds // 60}m"


def _schedule_summary_line(schedule: ScheduleRecord) -> str:
    preview = schedule.instruction.strip().replace("\n", " ")
    if len(preview) > 50:
        preview = preview[:50] + "…"
    return f"every {_format_interval(schedule.interval_seconds)} [{schedule.mode.value}] {preview}"


class ScheduleCommand(ConfirmableCommand):
    name = "/schedule"
    description = "Schedule a recurring read-only job or list and remove schedules"

    def execute(self, message: TelegramMessage, ctx: CommandContext) -> str:
        if ctx.schedule_store is None:
            return "Scheduling is not available."
        tokens = message.text.strip().split(maxsplit=3)
        if len(tokens) == 1:
            return self._list_schedules(message, ctx)
        if len(tokens) < 4:
            return format_usage(
                "/schedule",
                "/schedule <interval> <mode> <instruction>",
                "interval: 30m, 6h, 1d. mode: research, ask, or plan.",
            )

        interval_seconds = _parse_interval_seconds(tokens[1])
        if interval_seconds is None:
            return (
                "Interval must be like 30m, 6h, or 1d, and at least "
                f"{MIN_INTERVAL_SECONDS // 60}m."
            )
        mode = _SCHEDULABLE_MODES.get(tokens[2].strip().lower())
        if mode is None:
            return "Mode must be one of: research, ask, plan (read-only only)."
        instruction = tokens[3].strip()
        if not instruction:
            return "The instruction cannot be empty."

        project_name = effective_project_name_for_chat(ctx, message.chat_id)
        if not project_name:
            return "No project is registered. Add one in /projects."

        model = effective_model_for_chat(ctx, message.chat_id, project_name)
        schedule = ScheduleRecord(
            id=f"sch_{uuid4().hex[:10]}",
            project=project_name,
            chat_id=message.chat_id,
            requested_by=message.user_id,
            mode=mode,
            model=model,
            instruction=instruction,
            interval_seconds=interval_seconds,
        )
        ctx.schedule_store.create(schedule)
        return (
            f"Scheduled: {_schedule_summary_line(schedule)}\n"
            f"Project: {project_name}. The first run happens within the next poll."
        )

    def _list_schedules(self, message: TelegramMessage, ctx: CommandContext) -> str:
        project_name = effective_project_name_for_chat(ctx, message.chat_id)
        if not project_name:
            return "No project is registered. Add one in /projects."
        schedules = ctx.schedule_store.list_for_project_chat(project_name, message.chat_id)
        if not schedules:
            return (
                "No schedules yet. Add one with "
                "/schedule <interval> <mode> <instruction> (e.g. /schedule 6h research audit deps)."
            )
        lines = [f"- {_schedule_summary_line(s)}" for s in schedules]
        return "Scheduled jobs (tap to remove):\n" + "\n".join(lines)

    def get_inline_buttons(
        self,
        message: TelegramMessage | None = None,
        ctx: CommandContext | None = None,
    ) -> list[list[InlineButton]] | None:
        if message is None or ctx is None or ctx.schedule_store is None:
            return None
        # Confirmation step: show Yes/No for a pending delete.
        pending = ctx.confirmation_store.get(
            effective_project_name_for_chat(ctx, message.chat_id), message.chat_id
        )
        if pending is not None and pending.command_name == self.name:
            return [
                [
                    InlineButton("Yes, remove", f"{SCHEDULE_DELETE_PREFIX}:yes"),
                    InlineButton("No", f"{SCHEDULE_DELETE_PREFIX}:no"),
                ]
            ]
        if len(message.text.strip().split()) != 1:
            return None
        project_name = effective_project_name_for_chat(ctx, message.chat_id)
        if not project_name:
            return None
        schedules = ctx.schedule_store.list_for_project_chat(project_name, message.chat_id)
        buttons = [
            InlineButton(
                _schedule_summary_line(s)[:60], f"{SCHEDULE_DELETE_PREFIX}:ask:{s.id}"
            )
            for s in schedules
        ]
        return _button_rows(buttons, per_row=1) if buttons else None

    def confirm(
        self,
        message: TelegramMessage,
        ctx: CommandContext,
        pending: PendingConfirmation,
    ) -> str:
        if ctx.schedule_store is None:
            return "Scheduling is not available."
        if message.text.strip() != f"{SCHEDULE_DELETE_PREFIX}:yes":
            return "Schedule removal was cancelled."
        schedule_id = pending.action
        # Re-verify ownership before deleting: a schedule id from callback data must belong to this
        # chat and project, so no user can remove another chat's or project's schedule by id.
        project_name = effective_project_name_for_chat(ctx, message.chat_id)
        schedule = ctx.schedule_store.get(schedule_id)
        if (
            schedule is None
            or schedule.chat_id != message.chat_id
            or schedule.project != project_name
        ):
            return "That schedule no longer exists."
        removed = ctx.schedule_store.delete(schedule_id)
        return "Schedule removed." if removed else "That schedule no longer exists."
