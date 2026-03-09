# Copyright (c) 2025-2026 Sunet.
# Contributor: Kristofer Hallin
#
# This file is part of Sunet Scribe.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Add composite indexes to all tables.

Revision ID: d6f9b2c4e8a1
Revises: c5e8a1b3d7f2
Create Date: 2026-03-09 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "d6f9b2c4e8a1"
down_revision: Union[str, Sequence[str], None] = "c5e8a1b3d7f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEXES = [
    ("ix_job_results_job_id_user_id", "job_results", ["job_id", "user_id"]),
    ("ix_jobs_status_deletion_date", "jobs", ["status", "deletion_date"]),
    ("ix_group_user_link_group_id_user_id", "group_user_link", ["group_id", "user_id"]),
    ("ix_group_user_link_user_id_group_id", "group_user_link", ["user_id", "group_id"]),
    ("ix_group_model_link_group_id_model_id", "group_model_link", ["group_id", "model_id"]),
    ("ix_notifications_sent_user_id_uuid_type", "notifications_sent", ["user_id", "uuid", "notification_type"]),
]


def upgrade() -> None:
    """Upgrade schema."""

    engine = op.get_bind()
    inspector = inspect(engine)

    for index_name, table_name, columns in INDEXES:
        existing = {idx["name"] for idx in inspector.get_indexes(table_name)}
        if index_name not in existing:
            op.create_index(index_name, table_name, columns)


def downgrade() -> None:
    """Downgrade schema."""

    engine = op.get_bind()
    inspector = inspect(engine)

    for index_name, table_name, _columns in reversed(INDEXES):
        existing = {idx["name"] for idx in inspector.get_indexes(table_name)}
        if index_name in existing:
            op.drop_index(index_name, table_name=table_name)
