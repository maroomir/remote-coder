from __future__ import annotations

import re
from abc import ABC, abstractmethod
from datetime import UTC, datetime


class BranchNamingStrategy(ABC):
    @abstractmethod
    def make_branch_name(self, instruction: str) -> str:
        raise NotImplementedError


class TimestampSlugStrategy(BranchNamingStrategy):
    def make_branch_name(self, instruction: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", instruction.strip().lower()).strip("-")
        slug = slug or "task"
        if len(slug) > 30:
            slug = slug[:30].rstrip("-")
        ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        return f"remote-{slug}-{ts}"
