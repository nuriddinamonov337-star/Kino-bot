"""Database operations used by the admin panel."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Admin, MandatoryChannel, Movie, User

MOVIES_PER_PAGE = 10


async def movie_code_exists(session: AsyncSession, code: str) -> bool:
    return await session.scalar(select(Movie.id).where(Movie.code == code)) is not None


async def create_movie(session: AsyncSession, **values: object) -> Movie:
    movie = Movie(**values)
    session.add(movie)
    await session.flush()
    return movie


async def get_movie_by_code(session: AsyncSession, code: str) -> Movie | None:
    return await session.scalar(select(Movie).where(Movie.code == code, Movie.is_active.is_(True)))


async def soft_delete_movie(session: AsyncSession, movie_id: UUID) -> bool:
    movie = await session.get(Movie, movie_id)
    if movie is None or not movie.is_active:
        return False
    movie.is_active = False
    await session.flush()
    return True


async def list_movies(session: AsyncSession, page: int) -> tuple[list[Movie], int]:
    total = await session.scalar(select(func.count()).select_from(Movie)) or 0
    rows = await session.scalars(select(Movie).order_by(Movie.created_at.desc()).offset(page * MOVIES_PER_PAGE).limit(MOVIES_PER_PAGE))
    return list(rows), total


async def create_mandatory_channel(session: AsyncSession, *, chat_id: int, title: str, username: str | None, invite_url: str | None) -> MandatoryChannel:
    channel = await session.scalar(select(MandatoryChannel).where(MandatoryChannel.chat_id == chat_id))
    if channel is None:
        channel = MandatoryChannel(chat_id=chat_id, title=title, username=username, invite_url=invite_url)
        session.add(channel)
    else:
        channel.title, channel.username, channel.invite_url, channel.is_active = title, username, invite_url, True
    await session.flush()
    return channel


async def get_active_channel(session: AsyncSession, identifier: str) -> MandatoryChannel | None:
    query = select(MandatoryChannel).where(MandatoryChannel.is_active.is_(True))
    if identifier.startswith("@"):
        return await session.scalar(query.where(MandatoryChannel.username == identifier[1:]))
    return await session.scalar(query.where(MandatoryChannel.chat_id == int(identifier)))


async def soft_delete_channel(session: AsyncSession, channel_id: UUID) -> bool:
    channel = await session.get(MandatoryChannel, channel_id)
    if channel is None or not channel.is_active:
        return False
    channel.is_active = False
    await session.flush()
    return True


async def list_channels(session: AsyncSession) -> list[MandatoryChannel]:
    return list(await session.scalars(select(MandatoryChannel).order_by(MandatoryChannel.created_at.desc())))


async def dashboard_statistics(session: AsyncSession) -> dict[str, int]:
    now = datetime.now(UTC)
    async def count(statement):
        return await session.scalar(statement) or 0
    return {
        "users": await count(select(func.count()).select_from(User)),
        "active_users": await count(select(func.count()).select_from(User).where(User.is_active.is_(True))),
        "premium_users": await count(select(func.count()).select_from(User).where(User.premium_until > now)),
        "active_movies": await count(select(func.count()).select_from(Movie).where(Movie.is_active.is_(True))),
        "active_channels": await count(select(func.count()).select_from(MandatoryChannel).where(MandatoryChannel.is_active.is_(True))),
    }


async def list_database_admins(session: AsyncSession) -> list[Admin]:
    return list(await session.scalars(select(Admin).order_by(Admin.telegram_id)))
