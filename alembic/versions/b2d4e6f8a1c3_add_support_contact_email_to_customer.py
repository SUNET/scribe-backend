"""Add support_contact_email to customer table.

Revision ID: b2d4e6f8a1c3
Revises: f8b4c6d9e3a2
Create Date: 2026-03-13 10:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "b2d4e6f8a1c3"
down_revision: Union[str, Sequence[str], None] = "a9c5d7e1f4b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    engine = op.get_bind()
    inspector = inspect(engine)
    columns = [x["name"] for x in inspector.get_columns("customer")]

    if "support_contact_email" not in columns:
        op.add_column(
            "customer",
            sa.Column(
                "support_contact_email",
                sa.VARCHAR(),
                autoincrement=False,
                nullable=True,
            ),
        )


def downgrade() -> None:
    """Downgrade schema."""
    engine = op.get_bind()
    inspector = inspect(engine)
    columns = [x["name"] for x in inspector.get_columns("customer")]

    if "support_contact_email" in columns:
        op.drop_column("customer", "support_contact_email")
