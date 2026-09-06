"""Telegram bot process entry point."""

from __future__ import annotations

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


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log unexpected handler failures without terminating long polling."""
    logger.exception("Unhandled bot update error", exc_info=context.error)


async def on_startup(application: Application) -> None:
    queue: JobQueue = application.bot_data["queue"]
    connected = await queue.connect()
    if not connected:
        logger.error("Redis is unavailable. The bot will stay up; Reel jobs remain in PostgreSQL until a worker polls them.")
    health: HealthServer | None = application.bot_data.get("health")
    if health is not None:
        await health.start()


async def on_shutdown(application: Application) -> None:
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
