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

"""Add worker_health table.

Revision ID: c4d5e6f7a8b9
Revises: a3b4c5d6e7f8
Create Date: 2026-03-30 00:00:01.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "c4d5e6f7a8b9"
down_revision: Union[str, Sequence[str], None] = "a3b4c5d6e7f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    bind = op.get_bind()
    inspector = inspect(bind)

    if "worker_health" not in inspector.get_table_names():
        op.create_table(
            "worker_health",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("worker_id", sa.String(), nullable=False),
            sa.Column("load_avg", sa.Float(), nullable=False, server_default="0"),
            sa.Column("memory_usage", sa.Float(), nullable=False, server_default="0"),
            sa.Column("gpu_usage", sa.String(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )
        op.create_index("ix_worker_health_worker_id", "worker_health", ["worker_id"])
        op.create_index(
            "ix_worker_health_worker_id_created_at",
            "worker_health",
            ["worker_id", "created_at"],
        )


def downgrade() -> None:
    """Downgrade schema."""

    bind = op.get_bind()
    inspector = inspect(bind)

    if "worker_health" in inspector.get_table_names():
        op.drop_table("worker_health")
