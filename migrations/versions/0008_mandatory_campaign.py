"""Add subscriber-growth campaign columns to ``mandatory_channels`` (§13).

Each mandatory channel can optionally run a subscriber-growth campaign: the bot
counts every new user who joins the channel and completes the campaign once the
target is reached. This migration is idempotent: it only adds the columns that
are missing, so it is safe on databases that already have some of them.

New columns:

    campaign_target, campaign_current, campaign_status, campaign_price,
    campaign_started_at, campaign_completed_at
"""

import sqlalchemy as sa
from alembic import op

revision = "0008_mandatory_campaign"
down_revision = "0007_ad_campaigns"
branch_labels = None
depends_on = None

_COLUMNS = (
    ("campaign_target", sa.Integer(), "0"),
    ("campaign_current", sa.Integer(), "0"),
    ("campaign_status", sa.String(length=32), "none"),
    ("campaign_price", sa.Integer(), "0"),
    ("campaign_started_at", sa.DateTime(timezone=True), None),
    ("campaign_completed_at", sa.DateTime(timezone=True), None),
)


def _existing_columns(bind, table: str) -> set[str]:
    inspector = sa.inspect(bind)
    if table not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    existing = _existing_columns(bind, "mandatory_channels")
    if not existing:
        # Table is created by an earlier migration; nothing to alter.
        return
    for name, column_type, server_default in _COLUMNS:
        if name in existing:
            continue
        op.add_column(
            "mandatory_channels",
            sa.Column(name, column_type, nullable=True, server_default=server_default),
        )
    # Backfill NULLs then enforce NOT NULL on the non-nullable columns.
    op.execute("UPDATE mandatory_channels SET campaign_target = 0 WHERE campaign_target IS NULL")
    op.execute("UPDATE mandatory_channels SET campaign_current = 0 WHERE campaign_current IS NULL")
    op.execute("UPDATE mandatory_channels SET campaign_status = 'none' WHERE campaign_status IS NULL")
    op.execute("UPDATE mandatory_channels SET campaign_price = 0 WHERE campaign_price IS NULL")
    for name in ("campaign_target", "campaign_current", "campaign_status", "campaign_price"):
        op.alter_column("mandatory_channels", name, nullable=False)


def downgrade() -> None:
    bind = op.get_bind()
    existing = _existing_columns(bind, "mandatory_channels")
    for name, _column_type, _server_default in reversed(_COLUMNS):
        if name in existing:
            op.drop_column("mandatory_channels", name)
