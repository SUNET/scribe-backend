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

"""Add auth_handoff table.

Holds one login's tokens for a minute, so the OIDC callback can redirect
with a single-use code instead of putting the id token and the refresh
token in the query string. Rows are deleted as they are redeemed; the
sweeper only ever sees abandoned logins.

Revision ID: a1c4e7f2b9d3
Revises: e4f1a9c7b3d2
Create Date: 2026-08-31 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "a1c4e7f2b9d3"
down_revision: Union[str, Sequence[str], None] = "c7e2a4b6d9f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    engine = op.get_bind()
    inspector = inspect(engine)

    if "auth_handoff" in inspector.get_table_names():
        return

    op.create_table(
        "auth_handoff",
        sa.Column("code_hash", sa.String(), nullable=False),
        sa.Column("id_token", sa.String(), nullable=False),
        sa.Column("refresh_token", sa.String(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("code_hash"),
    )

    op.create_index(
        "ix_auth_handoff_expires_at", "auth_handoff", ["expires_at"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""

    engine = op.get_bind()
    inspector = inspect(engine)

    if "auth_handoff" not in inspector.get_table_names():
        return

    op.drop_index("ix_auth_handoff_expires_at", table_name="auth_handoff")
    op.drop_table("auth_handoff")
