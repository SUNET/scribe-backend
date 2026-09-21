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

"""
Tests for the one-group-per-user rule in group_update, and for how the
async session treats a rejection like that: rolled back, not logged as an
error.

Runs the real get_async_session against an in-memory SQLite database.
"""

import os
import pytest
import pytest_asyncio

# Point to an in-memory SQLite database before importing any project modules
os.environ["API_DATABASE_URL"] = "sqlite://"

from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from db.group import GroupMembershipConflict, group_update
from db.models import Group, GroupUserLink, User
from db.session import RejectedOperation, get_async_session


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture()
async def factory():
    """A fresh in-memory async SQLite database for each test."""
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


@pytest_asyncio.fixture(autouse=True)
async def _patch_sessionmaker(factory):
    """Make the real get_async_session hand out sessions on the test database."""

    async def _get_async_sessionmaker():
        return factory

    with patch("db.session.get_async_sessionmaker", _get_async_sessionmaker):
        yield


@pytest.fixture()
def error_log():
    with patch("db.session.log.error") as error:
        yield error


async def _seed(factory) -> dict:
    """Two groups; alice is in "Admin", bob is in no group."""
    async with factory() as session:
        admin = Group(name="Admin", realm="kth.se", transcribed_seconds=0)
        other = Group(name="Other", realm="kth.se", transcribed_seconds=0)
        alice = User(user_id="u-alice", username="alice@kth.se", realm="kth.se", transcribed_seconds=0)
        bob = User(user_id="u-bob", username="bob@kth.se", realm="kth.se", transcribed_seconds=0)
        session.add_all([admin, other, alice, bob])
        await session.flush()
        session.add(GroupUserLink(group_id=admin.id, user_id=alice.id))
        await session.commit()
        return {"admin": admin.id, "other": other.id, "alice": alice.id, "bob": bob.id}


async def _members(factory, group_id: int) -> set[int]:
    async with factory() as session:
        result = await session.execute(
            select(GroupUserLink.user_id).where(GroupUserLink.group_id == group_id)
        )
        return set(result.scalars().all())


# ---------------------------------------------------------------------------
# One group per user
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_adding_a_user_from_another_group_is_rejected(factory):
    ids = await _seed(factory)

    with pytest.raises(GroupMembershipConflict, match='already in the group "Admin"'):
        await group_update(ids["other"], usernames=["alice@kth.se"])


@pytest.mark.asyncio
async def test_a_rejected_update_changes_nothing(factory):
    """The name change and bob's membership come in the same request as the
    conflict, so they must be rolled back with it."""
    ids = await _seed(factory)

    with pytest.raises(GroupMembershipConflict):
        await group_update(
            ids["other"], name="Renamed", usernames=["bob@kth.se", "alice@kth.se"]
        )

    assert await _members(factory, ids["other"]) == set()
    assert await _members(factory, ids["admin"]) == {ids["alice"]}
    async with factory() as session:
        assert (await session.get(Group, ids["other"])).name == "Other"


@pytest.mark.asyncio
async def test_adding_a_user_without_a_group_succeeds(factory):
    ids = await _seed(factory)

    assert await group_update(ids["other"], usernames=["bob@kth.se"])
    assert await _members(factory, ids["other"]) == {ids["bob"]}


# ---------------------------------------------------------------------------
# Session logging
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_rejected_update_is_not_logged_as_an_error(factory, error_log):
    ids = await _seed(factory)

    with pytest.raises(GroupMembershipConflict):
        await group_update(ids["other"], usernames=["alice@kth.se"])

    error_log.assert_not_called()


@pytest.mark.asyncio
async def test_session_rolls_back_a_rejected_operation_quietly(factory, error_log):
    with pytest.raises(RejectedOperation):
        async with get_async_session() as session:
            session.add(User(user_id="u-carol", username="carol@kth.se", realm="kth.se", transcribed_seconds=0))
            await session.flush()
            raise RejectedOperation("no")

    error_log.assert_not_called()
    async with factory() as session:
        assert (await session.execute(select(User))).scalars().all() == []


@pytest.mark.asyncio
async def test_session_still_logs_genuine_faults(error_log):
    """ValueError also comes from the crypto helpers and "Job not found"; those
    are real faults and must keep their traceback in the log."""
    with pytest.raises(ValueError):
        async with get_async_session():
            raise ValueError("Unexpected end of file while reading encrypted chunk")

    error_log.assert_called_once()
