import uuid

import pytest

from app.config import Settings
from app.queue import JobQueue
from app.workers.reels import retry_backoff


class FakeRedis:
    def __init__(self) -> None:
        self.queue: list[str] = []
        self.queued: set[str] = set()

    async def sadd(self, key: str, value: str) -> int:
        assert key == "cinestream:reel-jobs:queued"
        if value in self.queued:
            return 0
        self.queued.add(value)
        return 1

    async def sismember(self, key: str, value: str) -> int:
        assert key == "cinestream:reel-jobs:queued"
        return int(value in self.queued)

    async def lpush(self, key: str, value: str) -> int:
        assert key == "cinestream:reel-jobs"
        self.queue.insert(0, value)
        return len(self.queue)

    async def brpop(self, key: str, timeout: int) -> tuple[str, str] | None:
        assert key == "cinestream:reel-jobs"
        if not self.queue:
            return None
        return key, self.queue.pop()

    async def srem(self, key: str, value: str) -> int:
        assert key == "cinestream:reel-jobs:queued"
        existed = value in self.queued
        self.queued.discard(value)
        return int(existed)


@pytest.mark.asyncio
async def test_queue_deduplicates_until_job_is_dequeued() -> None:
    queue = JobQueue("redis://test")
    queue._redis = FakeRedis()
    queue.available = True
    job_id = uuid.uuid4()

    assert await queue.enqueue(job_id) is True
    assert await queue.enqueue(job_id) is False
    assert await queue.dequeue(timeout=0) == job_id
    assert await queue.enqueue(job_id) is True


def test_retry_backoff_is_exponential_and_bounded() -> None:
    assert [retry_backoff(attempt, 5, 30) for attempt in range(1, 5)] == [5, 10, 20, 30]
    assert retry_backoff(0, 5, 30) == 0


def test_worker_configuration_has_safe_defaults_and_limits() -> None:
    settings = Settings(
        bot_token="test-token",
        database_url="sqlite+aiosqlite:///test.db",
    )
    assert settings.worker_concurrency == 1
    assert settings.reel_job_max_attempts == 3
    assert settings.worker_retry_backoff_seconds == 5
    assert settings.worker_retry_backoff_max_seconds == 300

    with pytest.raises(ValueError):
        Settings(bot_token="test-token", database_url="sqlite+aiosqlite:///test.db", worker_concurrency=5)