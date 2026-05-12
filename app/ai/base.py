from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from app.jobs.schemas import JobMode


@dataclass
class RunnerInput:
    instruction: str
    cwd: Path
    timeout_seconds: int
    env: dict[str, str] | None = None
    cancel_event: threading.Event | None = field(default=None, compare=False)
    mode: JobMode = JobMode.AGENT


@dataclass
class RunnerResult:
    exit_code: int
    stdout: str
    stderr: str
    started_at: datetime
    finished_at: datetime


class AiRunner(ABC):
    name: str

    @abstractmethod
    def run(self, runner_input: RunnerInput) -> RunnerResult:
        raise NotImplementedError
