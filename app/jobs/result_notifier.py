from __future__ import annotations

from collections.abc import Callable

from app.jobs.heartbeat import HeartbeatHandle, start_heartbeat
from app.jobs.schemas import Job, JobRequest
from app.jobs.store import JobStore
from app.monitoring.events import EventLogger
from app.telegram.notifier import Notifier

_joblog = EventLogger("app.jobs.lifecycle", "job.lifecycle")

# Telegram only allows reactions from a fixed allow-list of emoji, so map the job
# lifecycle onto values from https://core.telegram.org/bots/api#reactiontypeemoji.
REACTION_QUEUED = "👀"
REACTION_SUCCEEDED = "🎉"
REACTION_FAILED = "💔"
REACTION_CANCELLED = "🤝"

TERMINAL_REACTION_BY_STATUS = {
    "succeeded": REACTION_SUCCEEDED,
    "failed": REACTION_FAILED,
    "cancelled": REACTION_CANCELLED,
}


class ResultNotifier:
    """Owns Telegram-facing job notifications: per-project notifier resolution,
    lifecycle reactions, result delivery, and heartbeat startup."""

    def __init__(
        self,
        notifier_resolver: Callable[[str], Notifier],
        job_store: JobStore,
        heartbeat_interval_seconds: float,
    ) -> None:
        self._notifier_resolver = notifier_resolver
        self._job_store = job_store
        self._heartbeat_interval_seconds = heartbeat_interval_seconds

    def notifier_for(self, project: str) -> Notifier:
        return self._notifier_resolver(project)

    def start_heartbeat(self, job: Job) -> HeartbeatHandle:
        return start_heartbeat(
            job=job,
            notifier_resolver=self.notifier_for,
            interval_seconds=self._heartbeat_interval_seconds,
        )

    @staticmethod
    def message_id_or_none(value: object) -> int | None:
        return value if isinstance(value, int) else None

    @staticmethod
    def message_ids_or_empty(value: object) -> list[int]:
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, int)]

    def send_result(self, job: Job) -> None:
        job.result_message_ids = self.message_ids_or_empty(
            self.notifier_for(job.request.project).send_job_result(job)
        )
        self._job_store.update(job)
        self.react(job.request, TERMINAL_REACTION_BY_STATUS.get(job.status.value))

    def react(self, request: JobRequest, emoji: str | None) -> None:
        if request.message_id is None or emoji is None:
            return
        try:
            self.notifier_for(request.project).set_reaction(
                request.chat_id, request.message_id, emoji
            )
        except Exception:  # pylint: disable=broad-except
            _joblog.exception(
                "set_reaction failed",
                chat_id=request.chat_id,
                project=request.project,
            )
