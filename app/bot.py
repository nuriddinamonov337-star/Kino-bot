"""Telegram bot process entry point."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from telegram import Update
from telegram.ext import Application, ContextTypes

from app.config import Settings, get_settings
from app.database.session import Database
from app.handlers import register_handlers
from app.health import HealthServer
from app.logging import configure_logging
from app.queue import JobQueue

logger = logging.getLogger(__name__)

WORKER_SHUTDOWN_TIMEOUT_SECONDS = 30.0


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log unexpected handler failures without terminating long polling."""
    logger.exception("Unhandled bot update error", exc_info=context.error)


def _log_worker_result(task: asyncio.Task) -> None:
    """Log background Reel worker termination (errors are never silent)."""
    if task.cancelled():
        logger.info("Reel background worker task cancelled")
        return
    exc = task.exception()
    if exc is not None:
        logger.exception("Reel background worker failed", exc_info=exc)
    else:
        logger.info("Reel background worker task finished")


async def on_startup(application: Application) -> None:
    queue: JobQueue = application.bot_data["queue"]
    connected = await queue.connect()
    if not connected:
        logger.error("Redis is unavailable. The bot will stay up; Reel jobs remain in PostgreSQL until a worker polls them.")
    health: HealthServer | None = application.bot_data.get("health")
    if health is not None:
        await health.start()
    from app.workers.ad_poster import start_worker as start_ad_poster
    from app.workers.reels import start_worker

    stop_event = asyncio.Event()
    application.bot_data["reel_worker_stop"] = stop_event
    worker_task = asyncio.create_task(start_worker(stop_event), name="reel-worker")
    worker_task.add_done_callback(_log_worker_result)
    application.bot_data["reel_worker_task"] = worker_task
    logger.info("Reel background worker scheduled")

    ad_stop_event = asyncio.Event()
    application.bot_data["ad_poster_stop"] = ad_stop_event
    ad_task = asyncio.create_task(start_ad_poster(ad_stop_event), name="ad-poster-worker")
    ad_task.add_done_callback(_log_worker_result)
    application.bot_data["ad_poster_task"] = ad_task
    logger.info("Ad poster background worker scheduled")


async def on_shutdown(application: Application) -> None:
    worker_task: asyncio.Task | None = application.bot_data.pop("reel_worker_task", None)
    stop_event: asyncio.Event | None = application.bot_data.pop("reel_worker_stop", None)
    if stop_event is not None:
        stop_event.set()
    if worker_task is not None:
        try:
            await asyncio.wait_for(asyncio.shield(worker_task), timeout=WORKER_SHUTDOWN_TIMEOUT_SECONDS)
        except TimeoutError:
            logger.error("Reel worker did not stop within %ss; cancelling", WORKER_SHUTDOWN_TIMEOUT_SECONDS)
            worker_task.cancel()
            try:
                await worker_task
            except (asyncio.CancelledError, Exception):
                logger.exception("Reel worker task ended with error after cancel")
        except asyncio.CancelledError:
            logger.info("Reel worker shutdown cancelled")
        except Exception:
            logger.exception("Reel worker task raised during shutdown")
    ad_task: asyncio.Task | None = application.bot_data.pop("ad_poster_task", None)
    ad_stop: asyncio.Event | None = application.bot_data.pop("ad_poster_stop", None)
    if ad_stop is not None:
        ad_stop.set()
    if ad_task is not None:
        try:
            await asyncio.wait_for(asyncio.shield(ad_task), timeout=WORKER_SHUTDOWN_TIMEOUT_SECONDS)
        except TimeoutError:
            logger.error("Ad poster worker did not stop within %ss; cancelling", WORKER_SHUTDOWN_TIMEOUT_SECONDS)
            ad_task.cancel()
            try:
                await ad_task
            except (asyncio.CancelledError, Exception):
                logger.exception("Ad poster worker task ended with error after cancel")
        except asyncio.CancelledError:
            logger.info("Ad poster worker shutdown cancelled")
        except Exception:
            logger.exception("Ad poster worker task raised during shutdown")
    health: HealthServer | None = application.bot_data.get("health")
    if health is not None:
        await health.stop()
    queue: JobQueue | None = application.bot_data.get("queue")
    if queue is not None:
        await queue.close()
    database: Database = application.bot_data["database"]
    await database.dispose()


def create_application(settings: Settings) -> Application:
    """Build the Telegram application without starting network polling."""
    application = (
        Application.builder()
        .token(settings.bot_token.get_secret_value())
        .post_init(on_startup)
        .post_shutdown(on_shutdown)
        .build()
    )
    database = Database(settings.database_url)
    application.bot_data["database"] = database
    application.bot_data["queue"] = JobQueue(settings.redis_url)
    application.bot_data["started_at"] = datetime.now(UTC)
    if settings.listen_port is not None:
        application.bot_data["health"] = HealthServer(database, settings.listen_port)
    application.add_error_handler(on_error)
    register_handlers(application)
    return application


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    logger.info("Starting CineStream AI bot in %s", settings.environment)
    create_application(settings).run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
