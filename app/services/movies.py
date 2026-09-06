"""Movie lookup rules."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Movie


async def find_active_movie_by_code(session: AsyncSession, code: str) -> Movie | None:
    return await session.scalar(select(Movie).where(Movie.code == code, Movie.is_active.is_(True)))
