"""Shared entry-gate rendering for command and message handlers."""

from telegram import Update
from telegram.ext import ContextTypes

from app.database.session import Database
from app.keyboards import main_menu, mandatory_subscription_keyboard
from app.services.subscriptions import check_mandatory_subscriptions, get_active_mandatory_channels
from app.services.users import has_active_premium, register_or_update_user


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
        channels = await get_active_mandatory_channels(session)

    result = await check_mandatory_subscriptions(context.bot, telegram_user.id, channels)
    if result.is_subscribed:
        await message.reply_text("Xush kelibsiz!", reply_markup=main_menu())
        return True

    blocked = result.missing + result.unavailable
    text = "Davom etish uchun quyidagi kanallarga obuna bo‘ling."
    if result.unavailable:
        text += " Ayrim kanallar tekshirilmadi; keyinroq qayta urinib ko‘ring."
    await message.reply_text(text, reply_markup=mandatory_subscription_keyboard(blocked))
    return False
