"""Concurrency-safe AIMLAPI key rotation with temporary skip on auth/quota errors."""

from __future__ import annotations

import logging
import time
from threading import Lock

logger = logging.getLogger(__name__)


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
                    if index in self._disabled_until:
                        logger.info(
                            "AIMLAPI key slot %d cooldown expired; reusing it (%d/%d available)",
                            index,
                            self._available_locked(now),
                            total,
                        )
                        del self._disabled_until[index]
                    self._index = (index + 1) % total
                    logger.debug("AIMLAPI key slot %d acquired", index)
                    return index, self._keys[index]
                remaining = until - now
                logger.debug("AIMLAPI key slot %d in cooldown for %.0fs more", index, remaining)
            logger.warning("All %d AIMLAPI key(s) are in cooldown", total)
            return None, None

    def disable(self, index: int, seconds: float | None = None) -> None:
        duration = seconds if seconds is not None else self._cooldown
        with self._lock:
            self._disabled_until[index] = time.monotonic() + duration
        logger.warning(
            "AIMLAPI key slot %d disabled for %.0fs (%d/%d still available)",
            index,
            duration,
            self.available_count(),
            len(self._keys),
        )

    def _available_locked(self, now: float) -> int:
        return sum(1 for index in range(len(self._keys)) if self._disabled_until.get(index, 0.0) <= now)

    def available_count(self, now: float | None = None) -> int:
        moment = now if now is not None else time.monotonic()
        with self._lock:
            return sum(1 for index in range(len(self._keys)) if self._disabled_until.get(index, 0.0) <= moment)
