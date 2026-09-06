"""Initial CineStream AI database schema.

Revision ID: 0001_initial_schema
Revises:
"""

from alembic import op
import sqlalchemy as sa

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None

payment_plan = sa.Enum("weekly", "monthly", name="payment_plan")
payment_status = sa.Enum("pending", "approved", "rejected", name="payment_status")
campaign_status = sa.Enum("pending", "active", "completed", "cancelled", name="campaign_status")
reel_job_status = sa.Enum("pending", "processing", "completed", "failed", name="reel_job_status")


def identifiers() -> list[sa.Column]:
    return [sa.Column("id", sa.Uuid(), primary_key=True, nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False)]


def upgrade() -> None:
    op.create_table("users", *identifiers(), sa.Column("telegram_id", sa.BigInteger(), nullable=False), sa.Column("username", sa.String(255)), sa.Column("first_name", sa.String(255), nullable=False), sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False), sa.Column("premium_until", sa.DateTime(timezone=True)), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False), sa.UniqueConstraint("telegram_id"))
    op.create_index("ix_users_telegram_id", "users", ["telegram_id"])
    op.create_table("movies", *identifiers(), sa.Column("code", sa.String(64), nullable=False), sa.Column("title", sa.String(500), nullable=False), sa.Column("description", sa.Text()), sa.Column("poster_file_id", sa.String(512)), sa.Column("telegram_file_id", sa.String(512)), sa.Column("source_url", sa.String(2048)), sa.Column("main_channel_message_id", sa.BigInteger()), sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False), sa.UniqueConstraint("code"))
    op.create_index("ix_movies_code", "movies", ["code"])
    op.create_table("mandatory_channels", *identifiers(), sa.Column("chat_id", sa.BigInteger(), nullable=False), sa.Column("title", sa.String(255), nullable=False), sa.Column("username", sa.String(255)), sa.Column("invite_url", sa.String(2048)), sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False), sa.UniqueConstraint("chat_id"))
    op.create_table("admins", *identifiers(), sa.Column("telegram_id", sa.BigInteger(), nullable=False), sa.UniqueConstraint("telegram_id"))
    op.create_table("premium_payments", *identifiers(), sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False), sa.Column("plan", payment_plan, nullable=False), sa.Column("amount", sa.Integer(), nullable=False), sa.Column("receipt_file_id", sa.String(512)), sa.Column("status", payment_status, nullable=False), sa.Column("reviewed_by", sa.BigInteger()), sa.Column("reviewed_at", sa.DateTime(timezone=True)))
    op.create_table("subscriber_campaigns", *identifiers(), sa.Column("channel_id", sa.BigInteger(), nullable=False), sa.Column("channel_title", sa.String(255), nullable=False), sa.Column("channel_link", sa.String(2048), nullable=False), sa.Column("target_count", sa.Integer(), nullable=False), sa.Column("current_count", sa.Integer(), server_default="0", nullable=False), sa.Column("status", campaign_status, nullable=False), sa.Column("completed_at", sa.DateTime(timezone=True)))
    op.create_table("reels", *identifiers(), sa.Column("movie_id", sa.Uuid(), sa.ForeignKey("movies.id", ondelete="CASCADE"), nullable=False), sa.Column("telegram_file_id", sa.String(512), nullable=False), sa.Column("caption", sa.Text()))
    op.create_table("reel_jobs", *identifiers(), sa.Column("movie_id", sa.Uuid(), sa.ForeignKey("movies.id", ondelete="CASCADE"), nullable=False), sa.Column("status", reel_job_status, nullable=False), sa.Column("error", sa.Text()), sa.Column("attempts", sa.Integer(), server_default="0", nullable=False), sa.Column("completed_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    for table in ("reel_jobs", "reels", "subscriber_campaigns", "premium_payments", "admins", "mandatory_channels", "movies", "users"):
        op.drop_table(table)
    reel_job_status.drop(op.get_bind(), checkfirst=True)
    campaign_status.drop(op.get_bind(), checkfirst=True)
    payment_status.drop(op.get_bind(), checkfirst=True)
    payment_plan.drop(op.get_bind(), checkfirst=True)
