"""Manual Premium payment rules and safe status transitions."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import Settings
from app.database.models import PaymentPlan, PaymentStatus, PremiumPayment, User


class PendingPaymentExists(Exception):
    """Raised when a user attempts a second concurrent Premium payment."""


def is_premium_active(user: User, now: datetime | None = None) -> bool:
    if user.premium_until is None or user.premium_until.tzinfo is None:
        return False
    return user.premium_until > (now or datetime.now(UTC))


def plan_details(plan: PaymentPlan, settings: Settings) -> tuple[str, int, timedelta]:
    if plan is PaymentPlan.WEEKLY:
        return "1 hafta", settings.premium_weekly_price, timedelta(days=7)
    return "1 oy", settings.premium_monthly_price, timedelta(days=30)


def plan_duration(plan: PaymentPlan) -> timedelta:
    return timedelta(days=7 if plan is PaymentPlan.WEEKLY else 30)


async def create_pending_payment(session: AsyncSession, user: User, plan: PaymentPlan, settings: Settings) -> PremiumPayment:
    exists = await session.scalar(select(PremiumPayment.id).where(PremiumPayment.user_id == user.id, PremiumPayment.status == PaymentStatus.PENDING))
    if exists is not None:
        raise PendingPaymentExists
    _, amount, _ = plan_details(plan, settings)
    payment = PremiumPayment(user_id=user.id, plan=plan, amount=amount, status=PaymentStatus.PENDING)
    session.add(payment)
    await session.flush()
    return payment


async def attach_receipt(session: AsyncSession, payment_id: UUID, user_id: UUID, receipt_file_id: str) -> PremiumPayment | None:
    payment = await session.scalar(select(PremiumPayment).where(PremiumPayment.id == payment_id, PremiumPayment.user_id == user_id, PremiumPayment.status == PaymentStatus.PENDING))
    if payment is None:
        return None
    payment.receipt_file_id = receipt_file_id
    await session.flush()
    return payment


async def cancel_unsubmitted_payment(session: AsyncSession, payment_id: UUID, user_id: UUID) -> None:
    payment = await session.scalar(select(PremiumPayment).where(PremiumPayment.id == payment_id, PremiumPayment.user_id == user_id, PremiumPayment.status == PaymentStatus.PENDING, PremiumPayment.receipt_file_id.is_(None)))
    if payment is not None:
        payment.status = PaymentStatus.REJECTED
        await session.flush()


async def review_payment(session: AsyncSession, payment_id: UUID, admin_telegram_id: int, approve: bool, now: datetime | None = None) -> PremiumPayment | None:
    """Atomically review a pending payment and extend Premium only when approved."""
    payment = await session.scalar(select(PremiumPayment).options(selectinload(PremiumPayment.user)).where(PremiumPayment.id == payment_id).with_for_update())
    if payment is None or payment.status != PaymentStatus.PENDING or payment.receipt_file_id is None:
        return None
    reviewed_at = now or datetime.now(UTC)
    payment.reviewed_by, payment.reviewed_at = admin_telegram_id, reviewed_at
    if approve:
        payment.status = PaymentStatus.APPROVED
        start = payment.user.premium_until if is_premium_active(payment.user, reviewed_at) else reviewed_at
        payment.user.premium_until = start + plan_duration(payment.plan)
    else:
        payment.status = PaymentStatus.REJECTED
    await session.flush()
    return payment


async def list_payments(session: AsyncSession, status: PaymentStatus | None, page: int, page_size: int = 10) -> tuple[list[PremiumPayment], int]:
    query = select(PremiumPayment).options(selectinload(PremiumPayment.user)).order_by(PremiumPayment.created_at.desc())
    if status is not None:
        query = query.where(PremiumPayment.status == status)
    from sqlalchemy import func
    total = await session.scalar(select(func.count()).select_from(query.subquery())) or 0
    return list(await session.scalars(query.offset(page * page_size).limit(page_size))), total
