from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.database.base import Base
from app.database.models import PaymentPlan, PaymentStatus, User
from app.services.premium import PendingPaymentExists, create_pending_payment, is_premium_active, plan_details, review_payment


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection: await connection.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as value: yield value
    await engine.dispose()


@pytest.fixture
def settings():
    return Settings(bot_token="x", database_url="sqlite+aiosqlite://", redis_url="redis://localhost", premium_weekly_price=10000, premium_monthly_price=15000, _env_file=None)


def test_plan_prices(settings) -> None:
    assert plan_details(PaymentPlan.WEEKLY, settings)[1] == 10000
    assert plan_details(PaymentPlan.MONTHLY, settings)[1] == 15000


@pytest.mark.asyncio
async def test_payment_creation_prevents_duplicate_pending(session, settings) -> None:
    user = User(telegram_id=1, first_name="A"); session.add(user); await session.flush()
    payment = await create_pending_payment(session, user, PaymentPlan.WEEKLY, settings)
    assert payment.status is PaymentStatus.PENDING
    with pytest.raises(PendingPaymentExists): await create_pending_payment(session, user, PaymentPlan.MONTHLY, settings)


@pytest.mark.asyncio
async def test_approve_reject_and_premium_extension(session, settings) -> None:
    user = User(telegram_id=2, first_name="B"); session.add(user); await session.flush()
    weekly = await create_pending_payment(session, user, PaymentPlan.WEEKLY, settings); weekly.receipt_file_id = "receipt"; await session.flush()
    now = datetime.now(UTC); approved = await review_payment(session, weekly.id, 99, True, now)
    assert approved.status is PaymentStatus.APPROVED and user.premium_until == now + timedelta(days=7)
    monthly = await create_pending_payment(session, user, PaymentPlan.MONTHLY, settings); monthly.receipt_file_id = "receipt2"; await session.flush()
    await review_payment(session, monthly.id, 99, True, now)
    assert user.premium_until == now + timedelta(days=37)
    rejected = await create_pending_payment(session, user, PaymentPlan.WEEKLY, settings); rejected.receipt_file_id = "receipt3"; await session.flush()
    assert (await review_payment(session, rejected.id, 99, False, now)).status is PaymentStatus.REJECTED


def test_expired_premium_is_not_active() -> None:
    user = User(telegram_id=3, first_name="C", premium_until=datetime.now(UTC) - timedelta(seconds=1))
    assert not is_premium_active(user)
