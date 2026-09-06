import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.base import Base
from app.database.models import Movie, ReelJobStatus
from app.queue import JobQueue
from app.services.reels import (
    claim_next_pending_job,
    claim_reel_job,
    create_reel_job_if_absent,
    mark_job_failed,
    retry_failed_job,
)
from app.utils.sanitize import sanitize_error


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as value:
        yield value
    await engine.dispose()


@pytest.mark.asyncio
async def test_duplicate_pending_job_is_prevented(session) -> None:
    movie = Movie(code="1", title="A", telegram_file_id="file")
    session.add(movie)
    await session.flush()
    first, created = await create_reel_job_if_absent(session, movie.id)
    second, created_again = await create_reel_job_if_absent(session, movie.id)
    assert created is True
    assert created_again is False
    assert first.id == second.id
    assert first.status is ReelJobStatus.PENDING


@pytest.mark.asyncio
async def test_claim_prevents_duplicate_processing(session) -> None:
    movie = Movie(code="2", title="B", telegram_file_id="file")
    session.add(movie)
    await session.flush()
    job, _ = await create_reel_job_if_absent(session, movie.id)
    claimed = await claim_reel_job(session, job.id, max_attempts=3)
    again = await claim_reel_job(session, job.id, max_attempts=3)
    assert claimed is not None
    assert claimed.status is ReelJobStatus.PROCESSING
    assert again is None


@pytest.mark.asyncio
async def test_failed_job_retry_and_sanitized_error(session) -> None:
    movie = Movie(code="3", title="C", telegram_file_id="file")
    session.add(movie)
    await session.flush()
    job, _ = await create_reel_job_if_absent(session, movie.id)
    await claim_reel_job(session, job.id, max_attempts=3)
    failed = await mark_job_failed(session, job.id, "Bearer SECRETKEY123 token boom", retry=True, max_attempts=3)
    assert failed.status is ReelJobStatus.PENDING
    assert "SECRETKEY123" not in (failed.error or "")
    await claim_reel_job(session, job.id, max_attempts=3)
    failed = await mark_job_failed(session, job.id, "still failing", retry=True, max_attempts=2)
    assert failed.status is ReelJobStatus.FAILED
    retried = await retry_failed_job(session, job.id)
    assert retried.status is ReelJobStatus.PENDING
    assert retried.attempts == 0


def test_sanitize_error_hides_card_and_password() -> None:
    text = sanitize_error("postgresql://user:supersecret@localhost:5432/db card 4242424242424242")
    assert "supersecret" not in text
    assert "4242424242424242" not in text


@pytest.mark.asyncio
async def test_queue_enqueue_is_deduplicated() -> None:
    queue = JobQueue("redis://localhost:6379/0")
    queue.available = True
    queue._redis = object()

    class FakeRedis:
        def __init__(self) -> None:
            self.calls = []

        async def sismember(self, *_args, **_kwargs):
            self.calls.append("sismember")
            return 1

        async def lpush(self, *_args, **_kwargs):
            self.calls.append("lpush")
            return 1

    fake = FakeRedis()
    queue._redis = fake
    job_id = __import__("uuid").uuid4()

    result = await queue.enqueue(job_id)
    assert result is False
    assert fake.calls == ["sismember"]


@pytest.mark.asyncio
async def test_retry_applies_backoff_before_claim(session) -> None:
    movie = Movie(code="retry", title="Retry", telegram_file_id="file")
    session.add(movie)
    await session.flush()
    job, _ = await create_reel_job_if_absent(session, movie.id)
    await claim_reel_job(session, job.id, max_attempts=3)
    failed = await mark_job_failed(session, job.id, "temporary failure", retry=True, max_attempts=3, backoff_seconds=60)
    assert failed.status is ReelJobStatus.PENDING
    assert failed.retry_after is not None
    next_job = await claim_next_pending_job(session, max_attempts=3)
    assert next_job is None


def test_worker_concurrency_has_safe_default() -> None:
    from app.config import Settings

    settings = Settings(bot_token="x", database_url="postgresql+asyncpg://u:p@localhost:5432/db")
    assert 1 <= settings.worker_concurrency <= 4
    assert settings.worker_retry_backoff_seconds >= 1
