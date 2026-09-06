"""Redis job queue with a PostgreSQL fallback when Redis is unavailable."""

from __future__ import annotations

import logging
from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)

REEL_QUEUE_KEY = "cinestream:reel-jobs"
REEL_QUEUED_KEY = "cinestream:reel-jobs:queued"


class JobQueue:
    def __init__(self, redis_url: str) -> None:
        self._url = redis_url
        self._redis: Redis | None = None
        self.available = False

    async def connect(self) -> bool:
        try:
            self._redis = Redis.from_url(self._url, decode_responses=True)
            await self._redis.ping()
            self.available = True
            logger.info("Redis queue is available")
            return True
        except RedisError:
            logger.error("Redis is unavailable; jobs will stay in PostgreSQL until a worker polls them")
            self.available = False
            if self._redis is not None:
                await self._redis.aclose()
            self._redis = None
            return False
        except Exception:
            logger.exception("Redis connection failed; jobs will stay in PostgreSQL until a worker polls them")
            self.available = False
            self._redis = None
            return False

    async def enqueue(self, job_id: UUID) -> bool:
        if self._redis is None or not self.available:
            return False
        try:
            if await self._redis.sismember(REEL_QUEUED_KEY, str(job_id)):
                return False
            added = await self._redis.sadd(REEL_QUEUED_KEY, str(job_id))
            if not added:
                return False
            await self._redis.lpush(REEL_QUEUE_KEY, str(job_id))
            return True
        except RedisError:
            await self._discard_queued_marker(job_id)
            logger.error("Redis enqueue failed; the job remains pending in PostgreSQL")
            self.available = False
            return False

    async def dequeue(self, timeout: int = 5) -> UUID | None:
        if self._redis is None or not self.available:
            return None
        try:
            item = await self._redis.brpop(REEL_QUEUE_KEY, timeout=timeout)
        except RedisError:
            logger.error("Redis dequeue failed")
            self.available = False
            return None
        if item is None:
            return None
        _, payload = item
        try:
            job_id = UUID(payload)
        except ValueError:
            logger.error("Ignoring malformed queue payload")
            return None
        try:
            await self._redis.srem(REEL_QUEUED_KEY, payload)
        except RedisError:
            logger.warning("Redis queue marker cleanup failed")
        return job_id

    async def _discard_queued_marker(self, job_id: UUID) -> None:
        if self._redis is None:
            return
        try:
            await self._redis.srem(REEL_QUEUED_KEY, str(job_id))
        except RedisError:
            logger.warning("Redis queue marker rollback failed")

    async def close(self) -> None:
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None
        self.available = False
