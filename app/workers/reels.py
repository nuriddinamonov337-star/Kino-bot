"""Background worker: Redis queue + PostgreSQL polling for Reel jobs."""

from __future__ import annotations

import asyncio
import logging
import signal
from uuid import UUID

from telegram import Bot

from app.config import get_settings
from app.database.session import Database
from app.logging import configure_logging
from app.queue import JobQueue
from app.services.reels import claim_next_pending_job, claim_reel_job
from app.video.pipeline import ReelPipeline

logger = logging.getLogger(__name__)


def retry_backoff(attempt: int, base_seconds: float, max_seconds: float) -> float:
    """Return bounded exponential delay before the next retry."""
    if attempt < 1:
        return 0.0
    return min(max_seconds, base_seconds * (2 ** (attempt - 1)))


async def process_one(pipeline: ReelPipeline, database: Database, job_id: UUID, max_attempts: int) -> None:
    async with database.session() as session:
        async with session.begin():
            claimed = await claim_reel_job(session, job_id, max_attempts)
    if claimed is None:
        logger.info("Skipping job that is not pending")
        return
    await pipeline.run_job(job_id)


async def worker_loop(stop: asyncio.Event) -> None:
    settings = get_settings()
    database = Database(settings.database_url)
    queue = JobQueue(settings.redis_url)
    await queue.connect()
    bot = Bot(settings.bot_token.get_secret_value())
    pipeline = ReelPipeline(settings, database, bot)
    logger.info("Reel worker started")
    try:
        while not stop.is_set():
            job_id = await queue.dequeue(timeout=5)
            if job_id is None:
                async with database.session() as session:
                    async with session.begin():
                        claimed = await claim_next_pending_job(session, settings.reel_job_max_attempts)
                if claimed is None:
                    try:
                        await asyncio.wait_for(stop.wait(), timeout=2)
                    except TimeoutError:
                        pass
                    continue
                await pipeline.run_job(claimed.id)
                continue
            await process_one(pipeline, database, job_id, settings.reel_job_max_attempts)
    finally:
        logger.info("Reel worker shutting down")
        await queue.close()
        await database.dispose()


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    stop = asyncio.Event()

    def request_stop(*_args: object) -> None:
        stop.set()

    try:
        signal.signal(signal.SIGINT, request_stop)
        signal.signal(signal.SIGTERM, request_stop)
    except (NotImplementedError, ValueError):
        pass
    asyncio.run(_run(stop))


async def _run(stop: asyncio.Event) -> None:
    await worker_loop(stop)


if __name__ == "__main__":
    main()
