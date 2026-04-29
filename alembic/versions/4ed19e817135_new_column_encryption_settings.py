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

"""New column encryption_settings

Revision ID: 4ed19e817135
Revises: 3b0bf1328e70
Create Date: 2025-12-30 22:09:41.536137

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "4ed19e817135"
down_revision: Union[str, Sequence[str], None] = "3b0bf1328e70"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    engine = op.get_bind()
    inspector = inspect(engine)
    columns = [x["name"] for x in inspector.get_columns("users")]

    if "encryption_settings" not in columns:
        op.add_column(
            "users",
            sa.Column("encryption_settings", sa.BOOLEAN(), nullable=True),
        )
    if "private_key" not in columns:
        op.add_column(
            "users",
            sa.Column("private_key", sa.VARCHAR(), nullable=True),
        )
    if "public_key" not in columns:
        op.add_column("users", sa.Column("public_key", sa.VARCHAR(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    engine = op.get_bind()
    inspector = inspect(engine)
    columns = [x["name"] for x in inspector.get_columns("users")]

    if "encryption_settings" in columns:
        op.drop_column("users", "encryption_settings")
    if "private_key" in columns:
        op.drop_column("users", "private_key")
    if "public_key" in columns:
        op.drop_column("users", "public_key")
