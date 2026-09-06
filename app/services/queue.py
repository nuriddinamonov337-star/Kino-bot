"""Application queue facade built on the existing Redis and database services."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.queue import JobQueue
from app.services.reels import create_reel_job_if_absent


async def enqueue_job(session: AsyncSession, queue: JobQueue, movie_id: UUID) -> UUID | None:
    """Create one database job and enqueue it when Redis is available."""
    job, created = await create_reel_job_if_absent(session, movie_id)
    if not created:
        return None
    await session.flush()
    await queue.enqueue(job.id)
    return job.id


async def dequeue_job(queue: JobQueue, timeout: int = 5) -> UUID | None:
    return await queue.dequeue(timeout=timeout)


__all__ = ["JobQueue", "dequeue_job", "enqueue_job"]