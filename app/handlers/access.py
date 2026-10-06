"""Shared entry-gate rendering for command and message handlers."""

import logging

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from app.config import get_settings
from app.database.session import Database
from app.keyboards import main_menu, mandatory_subscription_keyboard
from app.services.subscriptions import (
    check_mandatory_subscriptions,
    count_campaign_subscribers,
    get_active_mandatory_channels,
)
from app.services.users import has_active_premium, register_or_update_user

logger = logging.getLogger(__name__)


async def _notify_campaign_completion(context: ContextTypes.DEFAULT_TYPE, channels) -> None:
    """Tell admins when a subscriber-growth campaign reaches its target."""
    settings = get_settings()
    for channel in channels:
        text = (
            "✅ Majburiy kanal kampaniyasi yakunlandi!\n\n"
            f"📣 Kanal: {channel.title}\n"
            f"🎯 Maqsad: {channel.campaign_target} ta obunachi\n"
            f"💰 Narx: {channel.campaign_price:,} so'm"
        )
        for admin_id in settings.admin_ids:
            try:
                await context.bot.send_message(admin_id, text)
            except TelegramError:
                logger.exception("Failed to notify admin %s about campaign completion", admin_id)



async def grant_or_request_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Register the user and return whether they may access bot content."""
    telegram_user = update.effective_user
    message = update.effective_message
    if telegram_user is None or message is None:
        return False
    database: Database = context.application.bot_data["database"]
    async with database.session() as session:
        async with session.begin():
            user = await register_or_update_user(session, telegram_user)
        if has_active_premium(user):
            await message.reply_text("Xush kelibsiz!", reply_markup=main_menu())
            return True
        channels = await get_active_mandatory_channels(
            session, get_settings().required_channel_ids
        )

    result = await check_mandatory_subscriptions(context.bot, telegram_user.id, channels)
    if result.is_subscribed:
        # Count this user toward any active subscriber-growth campaign.
        async with database.session() as session:
            async with session.begin():
                completed = await count_campaign_subscribers(session, channels)
        if completed:
            await _notify_campaign_completion(context, completed)
        await message.reply_text("Xush kelibsiz!", reply_markup=main_menu())
        return True


    blocked = result.missing + result.unavailable
    text = "Davom etish uchun quyidagi kanallarga obuna bo‘ling."
    if result.unavailable:
        text += " Ayrim kanallar tekshirilmadi; keyinroq qayta urinib ko‘ring."
    await message.reply_text(text, reply_markup=mandatory_subscription_keyboard(blocked))
    return False
