"""Add composite indexes for query optimization.

Revision ID: b3c4d5e6f7a8
Revises: a1b2c3d4e5f6
Create Date: 2026-03-07 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "b3c4d5e6f7a8"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEXES = [
    ("ix_jobs_status_user_id", "jobs", ["status", "user_id"]),
    ("ix_jobs_deletion_date_status", "jobs", ["deletion_date", "status"]),
    ("ix_jobs_created_at_status", "jobs", ["created_at", "status"]),
    ("ix_job_results_user_id_job_id", "job_results", ["user_id", "job_id"]),
    ("ix_page_views_timestamp_path", "page_views", ["timestamp", "path"]),
]


def upgrade() -> None:
    """Add composite indexes."""

    engine = op.get_bind()
    inspector = inspect(engine)

    for index_name, table_name, columns in INDEXES:
        existing = [idx["name"] for idx in inspector.get_indexes(table_name)]
        if index_name not in existing:
            op.create_index(index_name, table_name, columns)


def downgrade() -> None:
    """Remove composite indexes."""

    engine = op.get_bind()
    inspector = inspect(engine)

    for index_name, table_name, _columns in INDEXES:
        existing = [idx["name"] for idx in inspector.get_indexes(table_name)]
        if index_name in existing:
            op.drop_index(index_name, table_name=table_name)
