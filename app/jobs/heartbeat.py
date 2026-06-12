from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import UTC, datetime

from app.jobs.schemas import Job
from app.telegram.notifier import Notifier, build_job_accepted_message, build_job_heartbeat_message


class HeartbeatHandle:
    def __init__(self, stop_event: threading.Event, thread: threading.Thread | None) -> None:
        self._stop = stop_event
        self._thread = thread

    def set(self) -> None:
        # Stop the heartbeat and wait for any in-flight edit so the caller's next
        # edit (send_job_result) wins the race for the same message_id.
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=15)


def start_heartbeat(
    *,
    job: Job,
    notifier_resolver: Callable[[str], Notifier],
    interval_seconds: float,
) -> HeartbeatHandle:
    # Periodically edit the "Job accepted" message so a long run shows live progress.
    # No-op when there is no message to edit (e.g. notifier returned no id).
    stop = threading.Event()
    if job.accepted_message_id is None:
        return HeartbeatHandle(stop, None)
    notifier = notifier_resolver(job.request.project)
    chat_id = job.request.chat_id
    message_id = job.accepted_message_id
    started = datetime.now(UTC)
    _, stop_buttons = build_job_accepted_message(job)

    def _beat() -> None:
        while not stop.wait(interval_seconds):
            elapsed_minutes = int((datetime.now(UTC) - started).total_seconds() // 60)
            text = build_job_heartbeat_message(job, elapsed_minutes)
            notifier.edit_message(chat_id, message_id, text, stop_buttons)

    thread = threading.Thread(target=_beat, daemon=True)
    thread.start()
    return HeartbeatHandle(stop, thread)
