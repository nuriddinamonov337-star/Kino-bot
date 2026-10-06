"""O'chirilgan kino kodini qayta ishlatish (Problem 1).

Bu testlar quyidagilarni tekshiradi:

* ``hard_delete_movie`` kino yozuvini BUTUNLAY o'chiradi;
* bog'liq ``reels`` va ``reel_jobs`` yozuvlari ham cascade o'chiriladi;
* o'chirilgandan keyin ``movie_code_exists`` o'sha kod uchun ``False`` qaytaradi;
* soft-delete qilingan (``is_active=False``) kino kodi ham bo'sh hisoblanadi.
"""

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.base import Base
from app.database.models import Movie, Reel, ReelJob, ReelJobStatus
from app.services.admin import (
    create_movie,
    hard_delete_movie,
    movie_code_exists,
    soft_delete_movie,
)


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as value:
        yield value
    await engine.dispose()


async def _count(session, model) -> int:
    return await session.scalar(select(func.count()).select_from(model)) or 0


@pytest.mark.asyncio
async def test_hard_delete_frees_code_for_reuse(session) -> None:
    movie = await create_movie(session, code="1001", title="Birinchi", telegram_file_id="file-a")
    await session.commit()
    assert await movie_code_exists(session, "1001") is True

    deleted = await hard_delete_movie(session, movie.id)
    await session.commit()
    assert deleted is not None

    # Kod endi bo'sh bo'lishi kerak.
    assert await movie_code_exists(session, "1001") is False

    # Xuddi shu kod bilan yangi kino yaratish mumkin.
    reused = await create_movie(session, code="1001", title="Ikkinchi", telegram_file_id="file-b")
    await session.commit()
    assert reused.code == "1001"
    assert await movie_code_exists(session, "1001") is True


@pytest.mark.asyncio
async def test_hard_delete_cascades_reels_and_jobs(session) -> None:
    movie = await create_movie(session, code="2002", title="Cascade", telegram_file_id="file-c")
    await session.flush()
    session.add_all(
        [
            Reel(movie_id=movie.id, telegram_file_id="reel-1"),
            Reel(movie_id=movie.id, telegram_file_id="reel-2"),
            ReelJob(movie_id=movie.id, status=ReelJobStatus.PENDING),
        ]
    )
    await session.commit()
    assert await _count(session, Reel) == 2
    assert await _count(session, ReelJob) == 1

    await hard_delete_movie(session, movie.id)
    await session.commit()

    assert await _count(session, Movie) == 0
    assert await _count(session, Reel) == 0
    assert await _count(session, ReelJob) == 0


@pytest.mark.asyncio
async def test_soft_deleted_code_is_reusable(session) -> None:
    movie = await create_movie(session, code="3003", title="Soft", telegram_file_id="file-d")
    await session.commit()
    assert await soft_delete_movie(session, movie.id) is True
    await session.commit()

    # Soft-delete qilingan kino kodi band hisoblanmasligi kerak.
    assert await movie_code_exists(session, "3003") is False

    reused = await create_movie(session, code="3003", title="Qayta", telegram_file_id="file-e")
    await session.commit()
    assert reused.code == "3003"


@pytest.mark.asyncio
async def test_hard_delete_missing_movie_returns_none(session) -> None:
    from uuid import uuid4

    assert await hard_delete_movie(session, uuid4()) is None
