"""Database operations used by the admin panel."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    AdCampaign,
    AdStatus,
    Admin,
    MandatoryChannel,
    Movie,
    PaymentStatus,
    PremiumPayment,
    Reel,
    ReelJob,
    ReelJobStatus,
    User,
)

MOVIES_PER_PAGE = 10


async def movie_code_exists(session: AsyncSession, code: str) -> bool:
    """Return True only when an *active* movie already uses ``code``.

    Inactive (soft-deleted) rows are ignored so a code can be reused after a
    movie is removed. Hard-deleted rows are gone entirely, so their codes are
    always free again.
    """
    return (
        await session.scalar(
            select(Movie.id).where(Movie.code == code, Movie.is_active.is_(True))
        )
        is not None
    )


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


async def hard_delete_movie(session: AsyncSession, movie_id: UUID) -> Movie | None:
    """Permanently delete a movie and its Reels/ReelJobs (cascade).

    The related ``reels`` and ``reel_jobs`` rows are removed explicitly first so
    the delete works even when the database-level ``ON DELETE CASCADE`` is not
    present (e.g. SQLite in tests). This guarantees the ``movies.code`` unique
    value is freed and can be reused immediately.

    Returns the deleted movie (so callers can clean up the channel post) or
    ``None`` when the movie does not exist.
    """
    movie = await session.get(Movie, movie_id)
    if movie is None:
        return None
    # Explicit cascade: remove dependent rows before the parent movie row.
    await session.execute(delete(Reel).where(Reel.movie_id == movie_id))
    await session.execute(delete(ReelJob).where(ReelJob.movie_id == movie_id))
    await session.delete(movie)
    await session.flush()
    return movie


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


async def start_channel_campaign(
    session: AsyncSession,
    *,
    chat_id: int,
    title: str,
    username: str | None,
    invite_url: str | None,
    target: int,
    price: int,
    now: datetime | None = None,
) -> MandatoryChannel:
    """Create/reactivate a mandatory channel and start a subscriber campaign.

    The channel is upserted by ``chat_id`` (same rule as
    :func:`create_mandatory_channel`) and its campaign counters are reset so a
    fresh growth campaign begins immediately.
    """
    moment = now or datetime.now(UTC)
    channel = await session.scalar(select(MandatoryChannel).where(MandatoryChannel.chat_id == chat_id))
    if channel is None:
        channel = MandatoryChannel(chat_id=chat_id, title=title, username=username, invite_url=invite_url)
        session.add(channel)
    else:
        channel.title = title
        channel.username = username
        channel.invite_url = invite_url
        channel.is_active = True
    channel.campaign_target = target
    channel.campaign_current = 0
    channel.campaign_status = "active"
    channel.campaign_price = price
    channel.campaign_started_at = moment
    channel.campaign_completed_at = None
    await session.flush()
    return channel


async def increment_channel_campaign(
    session: AsyncSession, channel: MandatoryChannel, now: datetime | None = None
) -> bool:
    """Count one new subscriber; return True when the campaign just completed."""
    if channel.campaign_status != "active" or channel.campaign_target <= 0:
        return False
    channel.campaign_current += 1
    if channel.campaign_current >= channel.campaign_target:
        channel.campaign_status = "completed"
        channel.campaign_completed_at = now or datetime.now(UTC)
        await session.flush()
        return True
    await session.flush()
    return False


async def list_active_campaigns(session: AsyncSession) -> list[MandatoryChannel]:
    """Return channels with an in-progress subscriber campaign."""
    return list(
        await session.scalars(
            select(MandatoryChannel).where(MandatoryChannel.campaign_status == "active")
        )
    )



async def dashboard_statistics(session: AsyncSession) -> dict[str, int]:
    """Full admin statistics (§25): users, movies, reels, jobs, payments, ads."""
    now = datetime.now(UTC)

    async def count(statement):
        return await session.scalar(statement) or 0

    return {
        # Users
        "users": await count(select(func.count()).select_from(User)),
        "active_users": await count(select(func.count()).select_from(User).where(User.is_active.is_(True))),
        "premium_users": await count(select(func.count()).select_from(User).where(User.premium_until > now)),
        # Movies
        "movies": await count(select(func.count()).select_from(Movie)),
        "active_movies": await count(select(func.count()).select_from(Movie).where(Movie.is_active.is_(True))),
        # Channels
        "active_channels": await count(select(func.count()).select_from(MandatoryChannel).where(MandatoryChannel.is_active.is_(True))),
        # Reels & jobs
        "reels": await count(select(func.count()).select_from(Reel)),
        "reel_jobs": await count(select(func.count()).select_from(ReelJob)),
        "pending_jobs": await count(select(func.count()).select_from(ReelJob).where(ReelJob.status == ReelJobStatus.PENDING)),
        "failed_jobs": await count(select(func.count()).select_from(ReelJob).where(ReelJob.status == ReelJobStatus.FAILED)),
        # Premium payments
        "pending_payments": await count(select(func.count()).select_from(PremiumPayment).where(PremiumPayment.status == PaymentStatus.PENDING)),
        "approved_payments": await count(select(func.count()).select_from(PremiumPayment).where(PremiumPayment.status == PaymentStatus.APPROVED)),
        "revenue": await count(select(func.coalesce(func.sum(PremiumPayment.amount), 0)).where(PremiumPayment.status == PaymentStatus.APPROVED)),
        # Advertising
        "ad_requests": await count(select(func.count()).select_from(AdCampaign)),
        "pending_ads": await count(select(func.count()).select_from(AdCampaign).where(AdCampaign.status == AdStatus.PENDING)),
    }


async def list_database_admins(session: AsyncSession) -> list[Admin]:
    return list(await session.scalars(select(Admin).order_by(Admin.telegram_id)))


async def add_database_admin(session: AsyncSession, telegram_id: int) -> Admin:
    """Add a Telegram id to the DB admin list (idempotent)."""
    admin = await session.scalar(select(Admin).where(Admin.telegram_id == telegram_id))
    if admin is None:
        admin = Admin(telegram_id=telegram_id)
        session.add(admin)
        await session.flush()
    return admin


async def remove_database_admin(session: AsyncSession, telegram_id: int) -> bool:
    """Remove a Telegram id from the DB admin list. Returns True when removed."""
    admin = await session.scalar(select(Admin).where(Admin.telegram_id == telegram_id))
    if admin is None:
        return False
    await session.delete(admin)
    await session.flush()
    return True
