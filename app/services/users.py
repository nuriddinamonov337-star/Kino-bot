"""User registration and premium eligibility rules."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import User as TelegramUser

from app.database.models import User
from app.services.premium import is_premium_active


async def register_or_update_user(session: AsyncSession, telegram_user: TelegramUser) -> User:
    """Create one user once, or refresh mutable Telegram profile fields."""
    user = await session.scalar(select(User).where(User.telegram_id == telegram_user.id))
    if user is None:
        user = User(telegram_id=telegram_user.id, username=telegram_user.username, first_name=telegram_user.first_name or "")
        session.add(user)
    else:
        user.username = telegram_user.username
        user.first_name = telegram_user.first_name or ""
        user.is_active = True
    await session.flush()
    return user


def has_active_premium(user: User, now: datetime | None = None) -> bool:
    """Backward-compatible alias for the shared Premium eligibility rule."""
    return is_premium_active(user, now)
