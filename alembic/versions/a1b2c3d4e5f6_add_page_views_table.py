"""Add page_views table for analytics.

Revision ID: a1b2c3d4e5f6
Revises: 0c309fb6c471
Create Date: 2026-03-02 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "0c309fb6c471"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    engine = op.get_bind()
    inspector = inspect(engine)
    tables = inspector.get_table_names()

    if "page_views" not in tables:
        op.create_table(
            "page_views",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("path", sa.String(), nullable=False, index=True),
            sa.Column(
                "timestamp",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
                index=True,
            ),
        )


def downgrade() -> None:
    """Downgrade schema."""

    engine = op.get_bind()
    inspector = inspect(engine)
    tables = inspector.get_table_names()

    if "page_views" in tables:
        op.drop_table("page_views")
