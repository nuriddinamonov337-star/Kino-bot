"""Background worker: Redis queue + PostgreSQL polling for Reel jobs."""

from __future__ import annotations

import asyncio
import logging
import signal
from uuid import UUID

from telegram import Bot

from app.config import get_settings
from app.database.session import Database
from app.health import HealthServer
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


async def worker_loop(stop: asyncio.Event, health: HealthServer | None = None) -> None:
    settings = get_settings()
    database = Database(settings.database_url)
    queue = JobQueue(settings.redis_url)
    await queue.connect()
    bot = Bot(settings.bot_token.get_secret_value())
    pipeline = ReelPipeline(settings, database, bot)
    if health is not None:
        await health.start()
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
        if health is not None:
            await health.stop()
        await queue.close()
        await database.dispose()


async def start_worker(stop_event: asyncio.Event | None = None) -> None:
    """Run the Reel worker loop as a background task inside the bot process.

    Creates its own stop event when none is supplied so callers can simply
    ``await start_worker()`` or schedule it with ``asyncio.create_task``.
    Unexpected failures are logged (never silently swallowed) and re-raised
    so the caller's error handler can observe them.
    """
    stop = stop_event if stop_event is not None else asyncio.Event()
    logger.info("Reel background worker starting")
    try:
        await worker_loop(stop)
    except asyncio.CancelledError:
        logger.info("Reel background worker cancelled")
        raise
    except Exception:
        logger.exception("Reel background worker crashed")
        raise


def main() -> None:
    """Worker process entry point (``python -m app.workers.reels``).

    Starts an HTTP health server on ``PORT``/``HEALTH_PORT`` so Railway's
    healthcheck (``healthcheckPath = "/"``) succeeds. Without this the worker
    container is killed as unhealthy and crash-loops.
    """
    try:
        settings = get_settings()
    except Exception:
        # Log the real reason (missing BOT_TOKEN / DATABASE_URL, bad URL, ...)
        # instead of dying with a bare pydantic traceback.
        logging.basicConfig(level="ERROR", format="%(asctime)s | %(levelname)s | %(message)s", force=True)
        logger.exception(
            "Worker failed to start: invalid configuration. "
            "Check BOT_TOKEN, DATABASE_URL and REDIS_URL are set for this service."
        )
        raise SystemExit(1) from None
    configure_logging(settings.log_level)
    logger.info("Starting CineStream AI Reel worker in %s", settings.environment)
    stop = asyncio.Event()

    def request_stop(*_args: object) -> None:
        stop.set()

    try:
        signal.signal(signal.SIGINT, request_stop)
        signal.signal(signal.SIGTERM, request_stop)
    except (NotImplementedError, ValueError):
        pass
    asyncio.run(_run(stop, settings))


async def _run(stop: asyncio.Event, settings=None) -> None:
    if settings is None:
        settings = get_settings()
    health: HealthServer | None = None
    if settings.listen_port is not None:
        health = HealthServer(Database(settings.database_url), settings.listen_port)
    await worker_loop(stop, health)


if __name__ == "__main__":
    main()
