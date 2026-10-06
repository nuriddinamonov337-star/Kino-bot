"""PostgreSQL schema for CineStream AI."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.database.base import Base


def enum_values(enum_type: type[StrEnum]) -> list[str]:
    return [item.value for item in enum_type]


class PaymentPlan(StrEnum):
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class PaymentStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ReelJobStatus(StrEnum):

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class AdTariff(StrEnum):
    WEEK = "week"
    MONTH = "month"


class AdStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    ACTIVE = "active"
    COMPLETED = "completed"


class AdContentType(StrEnum):
    VIDEO = "video"
    PHOTO = "photo"
    DOCUMENT = "document"


class UUIDPrimaryKeyMixin:
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)


class CreatedAtMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class User(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "users"

    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    username: Mapped[str | None] = mapped_column(String(255))
    first_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    premium_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    premium_payments: Mapped[list[PremiumPayment]] = relationship(back_populates="user")
    ad_campaigns: Mapped[list[AdCampaign]] = relationship(back_populates="user")


class Movie(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "movies"

    # ``code`` is unique only among *active* movies (partial unique index below),
    # so a code can be reused after a movie is soft-deleted or hard-deleted.
    code: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    poster_file_id: Mapped[str | None] = mapped_column(String(512))
    telegram_file_id: Mapped[str | None] = mapped_column(String(512))
    telegram_file_unique_id: Mapped[str | None] = mapped_column(String(512))
    source_url: Mapped[str | None] = mapped_column(String(2048))
    main_channel_message_id: Mapped[int | None] = mapped_column(BigInteger)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    reels: Mapped[list[Reel]] = relationship(back_populates="movie", cascade="all, delete-orphan")
    reel_jobs: Mapped[list[ReelJob]] = relationship(back_populates="movie", cascade="all, delete-orphan")

    __table_args__ = (
        Index(
            "uq_movies_code_active",
            "code",
            unique=True,
            postgresql_where=text("is_active"),
            sqlite_where=text("is_active = 1"),
        ),
    )


class MandatoryChannel(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "mandatory_channels"
    chat_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    username: Mapped[str | None] = mapped_column(String(255))
    invite_url: Mapped[str | None] = mapped_column(String(2048))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")


class Admin(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "admins"
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)


class PremiumPayment(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "premium_payments"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    plan: Mapped[PaymentPlan] = mapped_column(
        Enum(PaymentPlan, name="payment_plan", values_callable=enum_values), nullable=False
    )
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    receipt_file_id: Mapped[str | None] = mapped_column(String(512))
    status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus, name="payment_status", values_callable=enum_values),
        nullable=False,
        default=PaymentStatus.PENDING,
    )
    reviewed_by: Mapped[int | None] = mapped_column(BigInteger)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user: Mapped[User] = relationship(back_populates="premium_payments")


class AdCampaign(Base):

    """Paid advertising campaign posted repeatedly to the ad channel (§12)."""

    __tablename__ = "ad_campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    tariff: Mapped[AdTariff] = mapped_column(
        Enum(AdTariff, name="ad_tariff", values_callable=enum_values), nullable=False
    )
    price: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_days: Mapped[int] = mapped_column(Integer, nullable=False)
    times_per_day: Mapped[int] = mapped_column(Integer, nullable=False)
    total_posts: Mapped[int] = mapped_column(Integer, nullable=False)
    posted_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    content_type: Mapped[AdContentType] = mapped_column(
        Enum(AdContentType, name="ad_content_type", values_callable=enum_values), nullable=False
    )
    file_id: Mapped[str] = mapped_column(String(512), nullable=False)
    caption: Mapped[str | None] = mapped_column(Text)
    status: Mapped[AdStatus] = mapped_column(
        Enum(AdStatus, name="ad_status", values_callable=enum_values),
        nullable=False,
        default=AdStatus.PENDING,
    )
    receipt_file_id: Mapped[str | None] = mapped_column(String(512))
    admin_message_id: Mapped[int | None] = mapped_column(BigInteger)
    next_post_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user: Mapped[User] = relationship(back_populates="ad_campaigns")


class Broadcast(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "broadcasts"

    admin_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", server_default="pending")
    sent_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Reel(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "reels"
    movie_id: Mapped[UUID] = mapped_column(ForeignKey("movies.id", ondelete="CASCADE"), nullable=False)
    telegram_file_id: Mapped[str] = mapped_column(String(512), nullable=False)
    caption: Mapped[str | None] = mapped_column(Text)
    start_seconds: Mapped[float | None] = mapped_column(Float)
    end_seconds: Mapped[float | None] = mapped_column(Float)
    reason: Mapped[str | None] = mapped_column(Text)
    movie: Mapped[Movie] = relationship(back_populates="reels")


class ReelJob(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "reel_jobs"
    movie_id: Mapped[UUID] = mapped_column(ForeignKey("movies.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[ReelJobStatus] = mapped_column(
        Enum(ReelJobStatus, name="reel_job_status", values_callable=enum_values),
        nullable=False,
        default=ReelJobStatus.PENDING,
    )
    error: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    retry_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    movie: Mapped[Movie] = relationship(back_populates="reel_jobs")


ReelsJob = ReelJob
