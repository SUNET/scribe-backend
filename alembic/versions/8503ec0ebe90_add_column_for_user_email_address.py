# Copyright (c) 2025-2026 Sunet.
# Contributor: Kristofer Hallin

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

"""Add column for user email address.

Revision ID: 8503ec0ebe90
Revises: 4ed19e817135
Create Date: 2026-01-05 16:59:46.548312

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "8503ec0ebe90"
down_revision: Union[str, Sequence[str], None] = "4ed19e817135"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    engine = op.get_bind()
    inspector = inspect(engine)
    columns = [x["name"] for x in inspector.get_columns("users")]

    if "email" not in columns:
        op.add_column(
            "users",
            sa.Column("email", sa.VARCHAR(), nullable=True),
        )


def downgrade() -> None:
    """Downgrade schema."""
    engine = op.get_bind()
    inspector = inspect(engine)
    columns = [x["name"] for x in inspector.get_columns("users")]

    if "email" in columns:
        op.drop_column("users", "email")
