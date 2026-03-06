# Copyright (c) 2025-2025 Sunet.
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

"""New column for customer base_fee.

Revision ID: 90af1e26ea70
Revises: 
Create Date: 2025-12-03 13:26:07.575947

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "90af1e26ea70"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    engine = op.get_bind()
    inspector = inspect(engine)
    columns = [x["name"] for x in inspector.get_columns("customer")]

    if "base_fee" not in columns:
        op.add_column(
            "customer",
            sa.Column("base_fee", sa.Integer(), nullable=True),
        )


def downgrade() -> None:
    """Downgrade schema."""

    engine = op.get_bind()
    inspector = inspect(engine)
    columns = [x["name"] for x in inspector.get_columns("customer")]

    if "base_fee" in columns:
        op.drop_column("customer", "base_fee")
