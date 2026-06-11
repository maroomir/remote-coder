from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import UTC, datetime

from app.jobs.schemas import Job
from app.telegram.notifier import Notifier, build_job_accepted_message, build_job_heartbeat_message


def start_heartbeat(
    *,
    job: Job,
    notifier_resolver: Callable[[str], Notifier],
    interval_seconds: float,
) -> threading.Event:
    # Periodically edit the "Job accepted" message so a long run shows live progress.
    # No-op when there is no message to edit (e.g. notifier returned no id).
    stop = threading.Event()
    if job.accepted_message_id is None:
        return stop
    notifier = notifier_resolver(job.request.project)
    chat_id = job.request.chat_id
    message_id = job.accepted_message_id
    started = datetime.now(UTC)
    accepted_text, stop_buttons = build_job_accepted_message(job)
    edited = threading.Event()

    def _beat() -> None:
        while not stop.wait(interval_seconds):
            elapsed_minutes = int((datetime.now(UTC) - started).total_seconds() // 60)
            text = build_job_heartbeat_message(job, elapsed_minutes)
            notifier.edit_message(chat_id, message_id, text, stop_buttons)
            edited.set()
        if edited.is_set():
            # Restore the original accepted body without the now-useless Stop button.
            notifier.edit_message(chat_id, message_id, accepted_text, [])

    threading.Thread(target=_beat, daemon=True).start()
    return stop
