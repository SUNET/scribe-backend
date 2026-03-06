# Copyright (c) 2025-2026 Sunet.
# Contributor: Kristofer Hallin
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

"""Add customer_abbr column to customer table.

Revision ID: 3b0bf1328e70
Revises: 90af1e26ea70
Create Date: 2025-12-16 09:27:31.237160

"""

from typing import Sequence, Union

import sqlalchemy as sa

from sqlalchemy import inspect

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "3b0bf1328e70"
down_revision: str = "90af1e26ea70"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    engine = op.get_bind()
    inspector = inspect(engine)
    columns = [x["name"] for x in inspector.get_columns("customer")]

    if "customer_abbr" not in columns:
        op.add_column(
            "customer",
            sa.Column(
                "customer_abbr", sa.VARCHAR(), autoincrement=False, nullable=True
            ),
        )


def downgrade() -> None:
    """Downgrade schema."""

    engine = op.get_bind()
    inspector = inspect(engine)
    columns = [x["name"] for x in inspector.get_columns("customer")]

    if "customer_abbr" in columns:
        op.drop_column("customer", "customer_abbr")
