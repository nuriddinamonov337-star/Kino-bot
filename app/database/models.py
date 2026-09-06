"""PostgreSQL schema for CineStream AI."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, Boolean, DateTime, Enum, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.database.base import Base


class PaymentPlan(StrEnum):
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class PaymentStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class CampaignStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ReelJobStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class AdvertisingType(StrEnum):
    SUBSCRIBERS = "subscribers"
    BOT = "bot"
    CHANNELS = "channels"
    CONTACT = "contact"


class AdvertisingStatus(StrEnum):
    PENDING = "pending"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


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
    advertising_requests: Mapped[list[AdvertisingRequest]] = relationship(back_populates="user")


class Movie(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "movies"

    code: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    poster_file_id: Mapped[str | None] = mapped_column(String(512))
    telegram_file_id: Mapped[str | None] = mapped_column(String(512))
    source_url: Mapped[str | None] = mapped_column(String(2048))
    main_channel_message_id: Mapped[int | None] = mapped_column(BigInteger)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    reels: Mapped[list[Reel]] = relationship(back_populates="movie", cascade="all, delete-orphan")
    reel_jobs: Mapped[list[ReelJob]] = relationship(back_populates="movie", cascade="all, delete-orphan")


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
    plan: Mapped[PaymentPlan] = mapped_column(Enum(PaymentPlan, name="payment_plan"), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    receipt_file_id: Mapped[str | None] = mapped_column(String(512))
    status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus, name="payment_status"), nullable=False, default=PaymentStatus.PENDING
    )
    reviewed_by: Mapped[int | None] = mapped_column(BigInteger)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user: Mapped[User] = relationship(back_populates="premium_payments")


class SubscriberCampaign(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "subscriber_campaigns"
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    channel_title: Mapped[str] = mapped_column(String(255), nullable=False)
    channel_link: Mapped[str] = mapped_column(String(2048), nullable=False)
    target_count: Mapped[int] = mapped_column(Integer, nullable=False)
    current_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    status: Mapped[CampaignStatus] = mapped_column(
        Enum(CampaignStatus, name="campaign_status"), nullable=False, default=CampaignStatus.PENDING
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


SubscriptionCampaign = SubscriberCampaign


class AdvertisingRequest(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "advertising_requests"

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    ad_type: Mapped[AdvertisingType] = mapped_column(
        Enum(AdvertisingType, name="advertising_type"), nullable=False
    )
    status: Mapped[AdvertisingStatus] = mapped_column(
        Enum(AdvertisingStatus, name="advertising_status"),
        nullable=False,
        default=AdvertisingStatus.PENDING,
    )
    details: Mapped[str] = mapped_column(Text, nullable=False)
    channel_title: Mapped[str | None] = mapped_column(String(255))
    channel_link: Mapped[str | None] = mapped_column(String(2048))
    target_count: Mapped[int | None] = mapped_column(Integer)
    campaign_id: Mapped[UUID | None] = mapped_column(Uuid)
    reviewed_by: Mapped[int | None] = mapped_column(BigInteger)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    admin_note: Mapped[str | None] = mapped_column(Text)
    user: Mapped[User] = relationship(back_populates="advertising_requests")


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
        Enum(ReelJobStatus, name="reel_job_status"), nullable=False, default=ReelJobStatus.PENDING
    )
    error: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    retry_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    movie: Mapped[Movie] = relationship(back_populates="reel_jobs")


ReelsJob = ReelJob
