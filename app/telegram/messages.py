from __future__ import annotations

from dataclasses import dataclass

from app.ai.model_catalog import format_model_selection
from app.ai.usage import format_token_usage
from app.jobs.plan_decisions import PLAN_EXECUTE_CALLBACK_PREFIX
from app.jobs.schemas import Job, JobMode, is_read_only_job_mode, job_mode_name
from app.telegram.i18n import ui_message


@dataclass
class OutboundButton:
    label: str
    callback_data: str
    style: str | None = None


def build_job_accepted_message(job: Job) -> tuple[str, list[list[OutboundButton]]]:
    mode_line = ""
    if is_read_only_job_mode(job.request.mode):
        mode_line = ui_message("job.mode_line", "\n- Mode: {mode}", mode=job_mode_name(job.request.mode))
    text = ui_message(
        "job.accepted",
        "✅ Job accepted\n\n"
        "- Job ID: {job_id}{session_line}\n"
        "- Project: {project}\n"
        "- Model: {model}{mode_line}",
        job_id=job.id,
        session_line=_ui_session_line(job),
        project=job.request.project,
        model=format_model_selection(job.request.model, job.request.model_id),
        mode_line=mode_line,
    )
    buttons = [
        [
            OutboundButton(
                ui_message("job.stop_button", "Stop job"),
                f"/stop {job.id}",
                style="danger",
            )
        ]
    ]
    return text, buttons


def build_job_heartbeat_message(job: Job, elapsed_minutes: int) -> str:
    accepted_text, _ = build_job_accepted_message(job)
    return ui_message(
        "job.heartbeat",
        "{accepted}\n\n⏳ Running ({minutes}m elapsed)",
        accepted=accepted_text,
        minutes=elapsed_minutes,
    )


def build_job_result_buttons(job: Job) -> list[list[OutboundButton]]:
    # A successful PLAN result can be turned into an AGENT implementation with one tap.
    if job.status.value == "succeeded" and job.request.mode is JobMode.PLAN:
        return [
            [
                OutboundButton(
                    ui_message("job.run_plan_button", "Run plan"),
                    f"{PLAN_EXECUTE_CALLBACK_PREFIX}:{job.id}",
                    style="primary",
                )
            ]
        ]
    if (
        job.status.value == "succeeded"
        and job.request.mode in (JobMode.AGENT, JobMode.AGENT_FIX)
        and job.branch
        and job.commit_hash
    ):
        return [
            [
                OutboundButton(
                    ui_message("job.open_pr_button", "Open PR"),
                    f"/pr {job.branch}",
                    style="primary",
                ),
                OutboundButton(
                    ui_message("job.rebase_button", "Rebase"),
                    f"/rebase {job.branch}",
                ),
            ]
        ]
    return []


def _ui_response_block(summary: str | None) -> str:
    if not summary:
        return ""
    return ui_message("job.response_block", "\n\nAI response:\n{summary}", summary=summary)


def _ui_failure_details(job: Job) -> str:
    details: list[str] = []
    if job.error_stage:
        details.append(
            ui_message("job.failure_detail_stage", "\n- Failure stage: {stage}", stage=job.error_stage)
        )
    if job.log_path:
        details.append(
            ui_message("job.failure_detail_log_path", "\n- Log path: {log_path}", log_path=job.log_path)
        )
    return "".join(details)


def _ui_failure_block(summary: str | None) -> str:
    if not summary:
        return ""
    return ui_message("job.failure_block", "\n\nFailure output summary:\n{summary}", summary=summary)


def _ui_token_usage(job: Job) -> str:
    return format_token_usage(job.runner_token_usage) or ui_message(
        "common.unavailable",
        "unavailable",
    )


def _ui_session_line(job: Job) -> str:
    session_id = job.request.session_id
    if not session_id:
        return ""
    return ui_message("job.session_line", "\n- Session ID: {session_id}", session_id=session_id)


def build_job_result_message(job: Job) -> str:
    mode_prefix = ""
    if job.request.mode is JobMode.PLAN:
        mode_prefix = "[plan] "
    elif job.request.mode is JobMode.ASK:
        mode_prefix = "[ask] "
    elif job.request.mode is JobMode.RESEARCH:
        mode_prefix = "[research] "

    if job.status.value == "cancelled":
        return ui_message(
            "job.cancelled",
            "{mode_prefix}⛔ Job cancelled\n\n- Job ID: {job_id}{session_line}\n- Project: {project}",
            mode_prefix=mode_prefix,
            job_id=job.id,
            session_line=_ui_session_line(job),
            project=job.request.project,
        )

    if job.status.value == "succeeded":
        if is_read_only_job_mode(job.request.mode):
            model_label = job.runner_actual_model or format_model_selection(
                job.request.model,
                job.request.model_id,
            )
            return ui_message(
                "job.readonly_completed",
                "[{mode}] Completed\n\n"
                "- Job ID: {job_id}{session_line}\n"
                "- Project: {project}\n"
                "- Model used: {model}\n"
                "- Token usage: {token_usage}{response_block}",
                mode=job_mode_name(job.request.mode),
                job_id=job.id,
                session_line=_ui_session_line(job),
                project=job.request.project,
                model=model_label,
                token_usage=_ui_token_usage(job),
                response_block=_ui_response_block(job.runner_stdout_summary),
            )

        changed = ", ".join(job.changed_files) if job.changed_files else ui_message(
            "job.no_changes",
            "No changes",
        )
        branch_line = job.branch if job.branch else ui_message(
            "job.branch_none_no_changes",
            "(none - no branch; no changes)",
        )
        commit_line = job.commit_hash or "-"
        if job.changed_files and not job.request.commit:
            commit_line = ui_message("job.no_commit_skipped", "(no commit - commit/push skipped)")
        elif job.changed_files and job.request.commit and not job.commit_hash:
            commit_line = ui_message("job.nothing_staged_skipped", "(nothing staged - push skipped)")
        model_label = job.runner_actual_model or format_model_selection(
            job.request.model,
            job.request.model_id,
        )
        return ui_message(
            "job.completed",
            "✅ Job completed\n\n"
            "- Job ID: {job_id}{session_line}\n"
            "- Project: {project}\n"
            "- Branch: {branch}\n"
            "- Commit: {commit}\n"
            "- Changed files: {changed}\n"
            "- Model used: {model}\n"
            "- Token usage: {token_usage}{response_block}",
            job_id=job.id,
            session_line=_ui_session_line(job),
            project=job.request.project,
            branch=branch_line,
            commit=commit_line,
            changed=changed,
            model=model_label,
            token_usage=_ui_token_usage(job),
            response_block=_ui_response_block(job.runner_stdout_summary),
        )

    failure_summary = job.runner_stderr_summary or job.runner_stdout_summary
    return ui_message(
        "job.failed",
        "{mode_prefix}❌ Job failed\n\n"
        "- Job ID: {job_id}{session_line}\n"
        "- Project: {project}\n"
        "- Error: {error}{details}{failure_block}",
        mode_prefix=mode_prefix,
        job_id=job.id,
        session_line=_ui_session_line(job),
        project=job.request.project,
        error=job.error or "unknown error",
        details=_ui_failure_details(job),
        failure_block=_ui_failure_block(failure_summary),
    )
