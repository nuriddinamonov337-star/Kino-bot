"""Authorization guard shared by all admin handlers."""

from functools import wraps
from typing import Awaitable, Callable, ParamSpec, TypeVar

from telegram import Update
from telegram.ext import ContextTypes

from app.config import get_settings
from app.database.session import Database
from app.services.permissions import is_admin

P = ParamSpec("P")
R = TypeVar("R")


async def admin_access(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    if user is None:
        return False
    database: Database = context.application.bot_data["database"]
    async with database.session() as session:
        allowed = await is_admin(session, user.id, get_settings().admin_ids)
    if not allowed:
        if update.callback_query:
            await update.callback_query.answer("Bu bo'lim faqat adminlar uchun.", show_alert=True)
        elif update.effective_message:
            await update.effective_message.reply_text("Bu bo'lim faqat adminlar uchun.")
    return allowed


def admin_only(handler: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R | None]]:
    @wraps(handler)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args: P.args, **kwargs: P.kwargs) -> R | None:
        if not await admin_access(update, context):
            return None
        return await handler(update, context, *args, **kwargs)
    return wrapped
