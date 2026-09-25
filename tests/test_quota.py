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
Tests for the monthly group quota in user_get_quota_left.

The quota used to be measured through the admin statistics, which are
scoped to the caller's admin_domains, so an ordinary user always saw zero
usage and was never stopped. These tests use ordinary users on purpose.

Runs the real get_async_session against an in-memory SQLite database.
"""

import os
import pytest
import pytest_asyncio

# Point to an in-memory SQLite database before importing any project modules
os.environ["API_DATABASE_URL"] = "sqlite://"

from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from db.models import Group, GroupUserLink, Job, JobStatusEnum, JobType, User
from db.user import user_get_quota_left


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


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def _seed(factory, quota_seconds, jobs=()) -> None:
    """
    One group with alice and bob, both ordinary users (no admin_domains).
    jobs is a list of (user_id, seconds, status, created_at).
    """
    async with factory() as session:
        group = Group(name="Group", realm="kth.se", quota_seconds=quota_seconds)
        alice = User(user_id="u-alice", username="alice@kth.se", realm="kth.se", transcribed_seconds=0)
        bob = User(user_id="u-bob", username="bob@kth.se", realm="kth.se", transcribed_seconds=0)
        session.add_all([group, alice, bob])
        await session.flush()
        session.add_all([
            GroupUserLink(group_id=group.id, user_id=alice.id),
            GroupUserLink(group_id=group.id, user_id=bob.id),
        ])
        for user_id, seconds, status, created_at in jobs:
            session.add(Job(
                uuid=str(uuid4()),
                user_id=user_id,
                status=status,
                job_type=JobType.TRANSCRIPTION,
                transcribed_seconds=seconds,
                created_at=created_at,
            ))
        await session.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ordinary_user_over_quota_is_stopped(factory):
    await _seed(factory, 600, [("u-alice", 600, JobStatusEnum.COMPLETED, _now())])

    assert await user_get_quota_left("u-alice") is False


@pytest.mark.asyncio
async def test_quota_is_shared_by_the_group(factory):
    """Alice used it all, so bob has none left either."""
    await _seed(factory, 600, [("u-alice", 600, JobStatusEnum.COMPLETED, _now())])

    assert await user_get_quota_left("u-bob") is False


@pytest.mark.asyncio
async def test_deleted_jobs_still_count(factory):
    await _seed(factory, 600, [("u-alice", 600, JobStatusEnum.DELETED, _now())])

    assert await user_get_quota_left("u-alice") is False


@pytest.mark.asyncio
async def test_under_quota_may_transcribe(factory):
    await _seed(factory, 600, [("u-alice", 599, JobStatusEnum.COMPLETED, _now())])

    assert await user_get_quota_left("u-alice") is True


@pytest.mark.asyncio
async def test_unfinished_jobs_do_not_count(factory):
    await _seed(factory, 600, [
        ("u-alice", 600, JobStatusEnum.PENDING, _now()),
        ("u-alice", 600, JobStatusEnum.FAILED, _now()),
    ])

    assert await user_get_quota_left("u-alice") is True


@pytest.mark.asyncio
async def test_last_month_does_not_count(factory):
    last_month = _now().replace(day=1) - timedelta(days=1)
    await _seed(factory, 600, [("u-alice", 6000, JobStatusEnum.COMPLETED, last_month)])

    assert await user_get_quota_left("u-alice") is True


@pytest.mark.asyncio
@pytest.mark.parametrize("quota_seconds", [None, 0])
async def test_group_without_quota_is_unlimited(factory, quota_seconds):
    """NULL used to reach `None / 60` and raise TypeError."""
    await _seed(factory, quota_seconds, [("u-alice", 6000, JobStatusEnum.COMPLETED, _now())])

    assert await user_get_quota_left("u-alice") is True


@pytest.mark.asyncio
async def test_user_without_group_is_unlimited(factory):
    await _seed(factory, 600)
    async with factory() as session:
        session.add(User(user_id="u-carol", username="carol@kth.se", realm="kth.se", transcribed_seconds=0))
        await session.commit()

    assert await user_get_quota_left("u-carol") is True
