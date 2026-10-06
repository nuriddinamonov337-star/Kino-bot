"""Background worker: posts due advertising campaigns to the ad channel (§12).

The worker polls PostgreSQL for ACTIVE campaigns whose ``next_post_at`` has
arrived, sends the stored content to ``REKLAMA_KANAL_ID`` and reschedules the
campaign (or completes it when ``total_posts`` is reached).
"""

from __future__ import annotations

import asyncio
import logging

from telegram import Bot
from telegram.error import TelegramError

from app.config import get_settings
from app.database.models import AdCampaign, AdContentType, AdStatus
from app.database.session import Database
from app.services.advertising import list_due_campaigns, record_post, tariff_label


logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 30.0


async def post_campaign(bot: Bot, channel_id: int, campaign: AdCampaign) -> bool:
    """Send one campaign post to the channel. Returns ``True`` on success."""
    caption = campaign.caption or None
    try:
        if campaign.content_type is AdContentType.VIDEO:
            await bot.send_video(channel_id, campaign.file_id, caption=caption)
        elif campaign.content_type is AdContentType.PHOTO:
            await bot.send_photo(channel_id, campaign.file_id, caption=caption)
        else:
            await bot.send_document(channel_id, campaign.file_id, caption=caption)
        return True
    except TelegramError:
        logger.exception("Failed to post ad campaign #%s to channel %s", campaign.id, channel_id)
        return False


async def run_once(bot: Bot, database: Database, channel_id: int) -> int:
    """Post all currently due campaigns. Returns the number posted."""
    settings = get_settings()
    async with database.session() as session:
        async with session.begin():
            due = await list_due_campaigns(session)
    posted = 0
    for campaign in due:
        if await post_campaign(bot, channel_id, campaign):
            async with database.session() as session:
                async with session.begin():
                    updated = await record_post(session, campaign.id, settings=settings)
            posted += 1
            if updated is not None and updated.status is AdStatus.COMPLETED:
                await _notify_completion(bot, updated)
    return posted


async def _notify_completion(bot: Bot, campaign: AdCampaign) -> None:
    """Tell the advertiser their campaign finished all scheduled posts."""
    if campaign.user is None:
        return
    try:
        await bot.send_message(
            campaign.user.telegram_id,
            "✅ Reklamangiz muvaffaqiyatli yakunlandi!\n\n"
            f"📦 Tarif: {tariff_label(campaign.tariff)}\n"
            f"📊 Jami: {campaign.total_posts} marta\n"
            f"🔢 Postlar: {campaign.posted_count} ta",
        )
    except TelegramError:
        logger.exception(
            "Failed to notify user %s about ad completion", campaign.user.telegram_id
        )



async def worker_loop(stop: asyncio.Event) -> None:
    settings = get_settings()
    channel_id = settings.reklama_kanal_id
    if channel_id is None:
        logger.error("REKLAMA_KANAL_ID is not configured; ad poster worker will not run")
        return
    database = Database(settings.database_url)
    bot = Bot(settings.bot_token.get_secret_value())
    logger.info("Ad poster worker started for channel %s", channel_id)
    try:
        while not stop.is_set():
            try:
                posted = await run_once(bot, database, channel_id)
                if posted:
                    logger.info("Posted %s advertising campaign(s)", posted)
            except Exception:
                logger.exception("Ad poster iteration failed")
            try:
                await asyncio.wait_for(stop.wait(), timeout=POLL_INTERVAL_SECONDS)
            except TimeoutError:
                pass
    finally:
        logger.info("Ad poster worker shutting down")
        await database.dispose()


async def start_worker(stop_event: asyncio.Event | None = None) -> None:
    """Run the ad poster loop as a background task inside the bot process."""
    stop = stop_event if stop_event is not None else asyncio.Event()
    logger.info("Ad poster background worker starting")
    try:
        await worker_loop(stop)
    except asyncio.CancelledError:
        logger.info("Ad poster background worker cancelled")
        raise
    except Exception:
        logger.exception("Ad poster background worker crashed")
        raise
