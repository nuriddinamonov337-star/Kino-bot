"""Add retry scheduling to reel jobs."""

from alembic import op
import sqlalchemy as sa


revision = "0003_reel_retry_after"
down_revision = "0002_advertising_and_reels"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("reel_jobs", sa.Column("retry_after", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("reel_jobs", "retry_after")