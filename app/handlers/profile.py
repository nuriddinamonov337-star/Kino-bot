"""User profile summary."""

from datetime import UTC

from telegram import Update
from telegram.ext import ContextTypes

from app.database.session import Database
from app.handlers.access import grant_or_request_subscription
from app.services.premium import is_premium_active
from app.services.users import register_or_update_user


async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await grant_or_request_subscription(update, context):
        return
    message, user = update.effective_message, update.effective_user
    if message is None or user is None:
        return
    database: Database = context.application.bot_data["database"]
    async with database.session() as session:
        async with session.begin():
            db_user = await register_or_update_user(session, user)
    if is_premium_active(db_user) and db_user.premium_until is not None:
        premium = f"💎 Premium: {db_user.premium_until.astimezone(UTC):%d.%m.%Y %H:%M}"
    else:
        premium = "💎 Premium: yo‘q"
    await message.reply_text(f"👤 Profil\n\nIsm: {db_user.first_name}\nID: {db_user.telegram_id}\n{premium}")
