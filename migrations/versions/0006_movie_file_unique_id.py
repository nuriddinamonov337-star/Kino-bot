"""Add telegram_file_unique_id and make movies.code unique only when active.

Two related changes:

1. ``movies.telegram_file_unique_id`` — stored alongside ``telegram_file_id``
   so download failures can be diagnosed (Problem 2).
2. Replace the plain ``UNIQUE`` constraint on ``movies.code`` with a *partial*
   unique index that only covers active rows. This lets an admin reuse a code
   after a movie is soft-deleted or hard-deleted (Problem 1).
"""

import sqlalchemy as sa
from alembic import op

revision = "0006_movie_file_unique_id"
down_revision = "0005_ad_campaigns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "movies",
        sa.Column("telegram_file_unique_id", sa.String(length=512), nullable=True),
    )
    # Drop the old full unique constraint (name may vary; use the conventional
    # SQLAlchemy-generated name) and add a partial unique index instead.
    with op.batch_alter_table("movies") as batch:
        batch.drop_constraint("movies_code_key", type_="unique")
    op.create_index(
        "uq_movies_code_active",
        "movies",
        ["code"],
        unique=True,
        postgresql_where=sa.text("is_active"),
        sqlite_where=sa.text("is_active = 1"),
    )


def downgrade() -> None:
    op.drop_index("uq_movies_code_active", table_name="movies")
    with op.batch_alter_table("movies") as batch:
        batch.create_unique_constraint("movies_code_key", ["code"])
    op.drop_column("movies", "telegram_file_unique_id")
