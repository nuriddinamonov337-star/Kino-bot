"""Ensure the paid advertising ``ad_campaigns`` table matches the final spec.

The ``ad_campaigns`` table was first introduced in ``0005_ad_campaigns``. This
migration is intentionally idempotent: it creates the table (and its enum
types) only when they are missing, so it is safe on databases that already ran
``0005`` and on fresh databases alike. It documents the canonical column set
for the paid advertising system (§12):

    id, user_id, tariff, price, duration_days, times_per_day, total_posts,
    posted_count, content_type, file_id, caption, status, receipt_file_id,
    admin_message_id, next_post_at, created_at, approved_at, completed_at
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007_ad_campaigns"
down_revision = "0006_movie_file_unique_id"
branch_labels = None
depends_on = None


def _table_exists(bind, name: str) -> bool:
    inspector = sa.inspect(bind)
    return name in inspector.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    if _table_exists(bind, "ad_campaigns"):
        # Already created by 0005; nothing to do.
        return

    ad_tariff = postgresql.ENUM("week", "month", name="ad_tariff")
    ad_content_type = postgresql.ENUM("video", "photo", "document", name="ad_content_type")
    ad_status = postgresql.ENUM(
        "pending", "approved", "rejected", "active", "completed", name="ad_status"
    )
    ad_tariff.create(bind, checkfirst=True)
    ad_content_type.create(bind, checkfirst=True)
    ad_status.create(bind, checkfirst=True)

    op.create_table(
        "ad_campaigns",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tariff", ad_tariff, nullable=False),
        sa.Column("price", sa.Integer(), nullable=False),
        sa.Column("duration_days", sa.Integer(), nullable=False),
        sa.Column("times_per_day", sa.Integer(), nullable=False),
        sa.Column("total_posts", sa.Integer(), nullable=False),
        sa.Column("posted_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("content_type", ad_content_type, nullable=False),
        sa.Column("file_id", sa.String(length=512), nullable=False),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column("status", ad_status, nullable=False),
        sa.Column("receipt_file_id", sa.String(length=512), nullable=True),
        sa.Column("admin_message_id", sa.BigInteger(), nullable=True),
        sa.Column("next_post_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if _table_exists(bind, "ad_campaigns"):
        op.drop_table("ad_campaigns")
    op.execute("DROP TYPE IF EXISTS ad_tariff")
    op.execute("DROP TYPE IF EXISTS ad_content_type")
    op.execute("DROP TYPE IF EXISTS ad_status")
