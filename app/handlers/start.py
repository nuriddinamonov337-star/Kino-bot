"""The /start handler."""

from telegram import Update
from telegram.ext import ContextTypes

from app.handlers.access import grant_or_request_subscription


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await grant_or_request_subscription(update, context)
