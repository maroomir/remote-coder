from __future__ import annotations

from collections import deque
from threading import Lock


class RecentUpdateTracker:
    def __init__(self, max_size: int = 1024) -> None:
        self._max_size = max_size
        self._seen: set[tuple[str, int]] = set()
        self._order: deque[tuple[str, int]] = deque()
        self._lock = Lock()

    def mark_seen(self, route_key: str, update_id: int) -> bool:
        key = (route_key, update_id)
        with self._lock:
            if key in self._seen:
                return True
            self._seen.add(key)
            self._order.append(key)
            while len(self._order) > self._max_size:
                old = self._order.popleft()
                self._seen.discard(old)
            return False

