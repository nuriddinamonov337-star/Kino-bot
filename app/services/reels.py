"""ReelJob lifecycle: enqueue, claim, retry, duplicate prevention."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import Movie, Reel, ReelJob, ReelJobStatus
from app.utils.sanitize import sanitize_error

ACTIVE_JOB_STATUSES = (ReelJobStatus.PENDING, ReelJobStatus.PROCESSING)


async def create_reel_job_if_absent(session: AsyncSession, movie_id: UUID) -> tuple[ReelJob, bool]:
    """Create a pending job unless one is already pending or processing.

    Returns ``(job, created)``.
    """
    existing = await session.scalar(
        select(ReelJob)
        .where(ReelJob.movie_id == movie_id, ReelJob.status.in_(ACTIVE_JOB_STATUSES))
        .order_by(ReelJob.created_at.desc())
    )
    if existing is not None:
        return existing, False
    job = ReelJob(movie_id=movie_id, status=ReelJobStatus.PENDING)
    session.add(job)
    await session.flush()
    return job, True


async def claim_reel_job(session: AsyncSession, job_id: UUID, max_attempts: int) -> ReelJob | None:
    """Atomically move a pending job to processing. Returns None if already claimed."""
    result = await session.execute(
        update(ReelJob)
        .where(
            ReelJob.id == job_id,
            ReelJob.status == ReelJobStatus.PENDING,
            ReelJob.attempts < max_attempts,
            (ReelJob.retry_after.is_(None) | (ReelJob.retry_after <= datetime.now(UTC))),
        )
        .values(status=ReelJobStatus.PROCESSING, attempts=ReelJob.attempts + 1)
        .returning(ReelJob)
    )
    return result.scalar_one_or_none()


async def claim_next_pending_job(session: AsyncSession, max_attempts: int) -> ReelJob | None:
    job = await session.scalar(
        select(ReelJob)
        .where(
            ReelJob.status == ReelJobStatus.PENDING,
            ReelJob.attempts < max_attempts,
            (ReelJob.retry_after.is_(None) | (ReelJob.retry_after <= datetime.now(UTC))),
        )
        .order_by(ReelJob.created_at.asc())
    )
    if job is None:
        return None
    return await claim_reel_job(session, job.id, max_attempts)


async def mark_job_completed(session: AsyncSession, job_id: UUID) -> None:
    job = await session.get(ReelJob, job_id)
    if job is None:
        return
    job.status = ReelJobStatus.COMPLETED
    job.error = None
    job.retry_after = None
    job.completed_at = datetime.now(UTC)
    await session.flush()


async def mark_job_failed(
    session: AsyncSession,
    job_id: UUID,
    error: str,
    *,
    retry: bool,
    max_attempts: int,
    backoff_seconds: float = 0,
    max_backoff_seconds: float | None = None,
) -> ReelJob | None:
    job = await session.get(ReelJob, job_id)
    if job is None:
        return None
    job.error = sanitize_error(error)
    if retry and job.attempts < max_attempts:
        job.status = ReelJobStatus.PENDING
        job.completed_at = None
        delay = max(0, backoff_seconds) * (2 ** max(0, job.attempts - 1))
        if max_backoff_seconds is not None:
            delay = min(delay, max_backoff_seconds)
        job.retry_after = datetime.now(UTC).replace(microsecond=0) + timedelta(seconds=delay)
    else:
        job.status = ReelJobStatus.FAILED
        job.completed_at = datetime.now(UTC)
        job.retry_after = None
    await session.flush()
    return job


async def retry_failed_job(session: AsyncSession, job_id: UUID) -> ReelJob | None:
    job = await session.get(ReelJob, job_id)
    if job is None or job.status != ReelJobStatus.FAILED:
        return None
    job.status = ReelJobStatus.PENDING
    job.attempts = 0
    job.retry_after = None
    job.completed_at = None
    await session.flush()
    return job


async def list_reel_jobs(session: AsyncSession, page: int, page_size: int = 10) -> tuple[list[ReelJob], int]:
    total = await session.scalar(select(func.count()).select_from(ReelJob)) or 0
    rows = await session.scalars(
        select(ReelJob)
        .options(selectinload(ReelJob.movie))
        .order_by(ReelJob.created_at.desc())
        .offset(page * page_size)
        .limit(page_size)
    )
    return list(rows), total


async def get_movie(session: AsyncSession, movie_id: UUID) -> Movie | None:
    return await session.get(Movie, movie_id)


async def save_reel(
    session: AsyncSession,
    *,
    movie_id: UUID,
    telegram_file_id: str,
    caption: str | None,
    start_seconds: float,
    end_seconds: float,
    reason: str,
) -> Reel:
    reel = Reel(
        movie_id=movie_id,
        telegram_file_id=telegram_file_id,
        caption=caption,
        start_seconds=start_seconds,
        end_seconds=end_seconds,
        reason=reason,
    )
    session.add(reel)
    await session.flush()
    return reel
