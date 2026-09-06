"""Reusable administrative authorization helper."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Admin


async def is_admin(session: AsyncSession, telegram_id: int, configured_ids: tuple[int, ...]) -> bool:
    if telegram_id in configured_ids:
        return True
    return await session.scalar(select(Admin.id).where(Admin.telegram_id == telegram_id)) is not None
