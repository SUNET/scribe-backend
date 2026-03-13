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

"""Add onboarding_attributes table.

Revision ID: a9c5d7e1f4b3
Revises: f8b4c6d9e3a2
Create Date: 2026-03-12 00:00:02.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "a9c5d7e1f4b3"
down_revision: Union[str, Sequence[str], None] = "f8b4c6d9e3a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    engine = op.get_bind()
    inspector = inspect(engine)

    if "onboarding_attributes" not in inspector.get_table_names():
        op.create_table(
            "onboarding_attributes",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("name", sa.String(), nullable=False, unique=True, index=True),
            sa.Column(
                "description", sa.String(), nullable=False, server_default=""
            ),
            sa.Column("example", sa.String(), nullable=False, server_default=""),
        )


def downgrade() -> None:
    """Downgrade schema."""

    engine = op.get_bind()
    inspector = inspect(engine)

    if "onboarding_attributes" in inspector.get_table_names():
        op.drop_table("onboarding_attributes")
