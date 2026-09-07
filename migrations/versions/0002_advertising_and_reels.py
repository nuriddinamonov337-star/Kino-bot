"""Add advertising requests and reel metadata columns.

Revision ID: 0002_advertising_and_reels
Revises: 0001_initial_schema
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_advertising_and_reels"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None

advertising_type = postgresql.ENUM("subscribers", "bot", "channels", "contact", name="advertising_type")
advertising_status = postgresql.ENUM(
    "pending", "in_review", "approved", "rejected", "completed", "cancelled", name="advertising_status"
)

advertising_type_column = postgresql.ENUM(
    "subscribers", "bot", "channels", "contact", name="advertising_type", create_type=False
)
advertising_status_column = postgresql.ENUM(
    "pending", "in_review", "approved", "rejected", "completed", "cancelled",
    name="advertising_status", create_type=False
)


def upgrade() -> None:
    advertising_type.create(op.get_bind(), checkfirst=True)
    advertising_status.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "advertising_requests",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("ad_type", advertising_type_column, nullable=False),
        sa.Column("status", advertising_status_column, nullable=False),
        sa.Column("details", sa.Text(), nullable=False),
        sa.Column("channel_title", sa.String(255)),
        sa.Column("channel_link", sa.String(2048)),
        sa.Column("target_count", sa.Integer()),
        sa.Column("campaign_id", sa.Uuid()),
        sa.Column("reviewed_by", sa.BigInteger()),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("admin_note", sa.Text()),
    )
    op.add_column("reels", sa.Column("start_seconds", sa.Float(), nullable=True))
    op.add_column("reels", sa.Column("end_seconds", sa.Float(), nullable=True))
    op.add_column("reels", sa.Column("reason", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("reels", "reason")
    op.drop_column("reels", "end_seconds")
    op.drop_column("reels", "start_seconds")
    op.drop_table("advertising_requests")
    advertising_status.drop(op.get_bind(), checkfirst=True)
    advertising_type.drop(op.get_bind(), checkfirst=True)
