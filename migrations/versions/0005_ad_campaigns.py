"""Replace the old advertising request system with paid ad campaigns (§12)."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0005_ad_campaigns"
down_revision = "0004_broadcasts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ad_campaigns",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tariff", sa.Enum("week", "month", name="ad_tariff"), nullable=False),
        sa.Column("price", sa.Integer(), nullable=False),
        sa.Column("duration_days", sa.Integer(), nullable=False),
        sa.Column("times_per_day", sa.Integer(), nullable=False),
        sa.Column("total_posts", sa.Integer(), nullable=False),
        sa.Column("posted_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "content_type",
            sa.Enum("video", "photo", "document", name="ad_content_type"),
            nullable=False,
        ),
        sa.Column("file_id", sa.String(length=512), nullable=False),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("pending", "approved", "rejected", "active", "completed", name="ad_status"),
            nullable=False,
        ),
        sa.Column("receipt_file_id", sa.String(length=512), nullable=True),
        sa.Column("admin_message_id", sa.BigInteger(), nullable=True),
        sa.Column("next_post_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.drop_table("advertising_requests")
    op.drop_table("subscriber_campaigns")
    op.execute("DROP TYPE IF EXISTS advertising_type")
    op.execute("DROP TYPE IF EXISTS advertising_status")
    op.execute("DROP TYPE IF EXISTS campaign_status")


def downgrade() -> None:
    op.create_table(
        "subscriber_campaigns",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("channel_title", sa.String(length=255), nullable=False),
        sa.Column("channel_link", sa.String(length=2048), nullable=False),
        sa.Column("target_count", sa.Integer(), nullable=False),
        sa.Column("current_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "status",
            sa.Enum("pending", "active", "completed", "cancelled", name="campaign_status"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "advertising_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "ad_type",
            sa.Enum("subscribers", "bot", "channels", "contact", name="advertising_type"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "in_review",
                "approved",
                "rejected",
                "completed",
                "cancelled",
                name="advertising_status",
            ),
            nullable=False,
        ),
        sa.Column("details", sa.Text(), nullable=False),
        sa.Column("channel_title", sa.String(length=255), nullable=True),
        sa.Column("channel_link", sa.String(length=2048), nullable=True),
        sa.Column("target_count", sa.Integer(), nullable=True),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reviewed_by", sa.BigInteger(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("admin_note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.drop_table("ad_campaigns")
    op.execute("DROP TYPE IF EXISTS ad_tariff")
    op.execute("DROP TYPE IF EXISTS ad_status")
    op.execute("DROP TYPE IF EXISTS ad_content_type")
