"""Concurrency-safe AIMLAPI key rotation with temporary skip on auth/quota errors."""

from __future__ import annotations

import time
from threading import Lock


class ApiKeyRotator:
    """Rotate through API keys and temporarily skip keys that failed with quota/auth errors.

    Multiple keys do not imply multiplied free quota; they only provide failover.
    """

    def __init__(self, keys: tuple[str, ...], cooldown_seconds: float = 120.0) -> None:
        if not keys:
            raise ValueError("At least one AIMLAPI key is required")
        self._keys = keys
        self._cooldown = cooldown_seconds
        self._disabled_until: dict[int, float] = {}
        self._index = 0
        self._lock = Lock()

    def __len__(self) -> int:
        return len(self._keys)

    def next_key(self) -> str:
        index, key = self.acquire()
        if key is None:
            raise RuntimeError("No AIMLAPI keys are currently available")
        return key

    def acquire(self) -> tuple[int | None, str | None]:
        """Return the next non-cooled-down key, or (None, None) if all are skipped."""
        now = time.monotonic()
        with self._lock:
            total = len(self._keys)
            for offset in range(total):
                index = (self._index + offset) % total
                until = self._disabled_until.get(index, 0.0)
                if until <= now:
                    self._index = (index + 1) % total
                    return index, self._keys[index]
            return None, None

    def disable(self, index: int, seconds: float | None = None) -> None:
        with self._lock:
            self._disabled_until[index] = time.monotonic() + (seconds if seconds is not None else self._cooldown)

    def available_count(self, now: float | None = None) -> int:
        moment = now if now is not None else time.monotonic()
        with self._lock:
            return sum(1 for index in range(len(self._keys)) if self._disabled_until.get(index, 0.0) <= moment)
