"""Callback handler for the mandatory-subscription recheck button."""

from telegram import Update
from telegram.ext import ContextTypes

from app.handlers.access import grant_or_request_subscription


async def recheck_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    # `effective_message` is the message that owns the inline keyboard.
    await grant_or_request_subscription(update, context)
