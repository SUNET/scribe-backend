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

"""Add composite indexes to page_views table.

Revision ID: c5e8a1b3d7f2
Revises: b3d7f9a2e1c4
Create Date: 2026-03-09 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "c5e8a1b3d7f2"
down_revision: Union[str, Sequence[str], None] = "b3d7f9a2e1c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    engine = op.get_bind()
    inspector = inspect(engine)
    existing_indexes = {idx["name"] for idx in inspector.get_indexes("page_views")}

    if "ix_page_views_timestamp_path" not in existing_indexes:
        op.create_index(
            "ix_page_views_timestamp_path",
            "page_views",
            ["timestamp", "path"],
        )

    if "ix_page_views_path_timestamp" not in existing_indexes:
        op.create_index(
            "ix_page_views_path_timestamp",
            "page_views",
            ["path", "timestamp"],
        )


def downgrade() -> None:
    """Downgrade schema."""

    engine = op.get_bind()
    inspector = inspect(engine)
    existing_indexes = {idx["name"] for idx in inspector.get_indexes("page_views")}

    if "ix_page_views_path_timestamp" in existing_indexes:
        op.drop_index("ix_page_views_path_timestamp", table_name="page_views")

    if "ix_page_views_timestamp_path" in existing_indexes:
        op.drop_index("ix_page_views_timestamp_path", table_name="page_views")
