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
Tests for group quota enforcement in user_get_quota_left.

Quota is a monthly budget for the whole group: the sum of completed
transcription jobs created this calendar month by the group's members.

Runs the real get_async_session against an in-memory SQLite database.
"""

import os
import pytest
import pytest_asyncio

# Point to an in-memory SQLite database before importing any project modules
os.environ["API_DATABASE_URL"] = "sqlite://"

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

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


async def _seed(factory, quota_seconds=600, members=("u-alice", "u-bob")) -> int:
    """One group in kth.se with the given quota and plain (non-admin) members."""
    async with factory() as session:
        group = Group(name="Course", realm="kth.se", quota_seconds=quota_seconds, transcribed_seconds=0)
        session.add(group)
        session.add(User(user_id="u-loner", username="loner@kth.se", realm="kth.se", transcribed_seconds=0))
        await session.flush()

        for user_id in members:
            user = User(user_id=user_id, username=f"{user_id}@kth.se", realm="kth.se", transcribed_seconds=0)
            session.add(user)
            await session.flush()
            session.add(GroupUserLink(group_id=group.id, user_id=user.id))

        await session.commit()
        return group.id


async def _job(factory, user_id, seconds, status=JobStatusEnum.COMPLETED, created_at=None):
    async with factory() as session:
        session.add(
            Job(
                user_id=user_id,
                job_type=JobType.TRANSCRIPTION,
                status=status,
                transcribed_seconds=seconds,
                created_at=created_at or _now(),
            )
        )
        await session.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_regular_user_over_quota_is_blocked(factory):
    """The bug: a member without admin_domains always read as 0 minutes used."""
    await _seed(factory, quota_seconds=600)
    await _job(factory, "u-alice", 600)

    assert await user_get_quota_left("u-alice") is False


@pytest.mark.asyncio
async def test_under_quota_is_allowed(factory):
    await _seed(factory, quota_seconds=600)
    await _job(factory, "u-alice", 599)

    assert await user_get_quota_left("u-alice") is True


@pytest.mark.asyncio
async def test_usage_is_shared_across_the_group(factory):
    """Bob has used nothing himself, but the group's budget is spent."""
    await _seed(factory, quota_seconds=600)
    await _job(factory, "u-alice", 400)
    await _job(factory, "u-bob", 200)

    assert await user_get_quota_left("u-bob") is False


@pytest.mark.asyncio
async def test_deleted_jobs_still_count(factory):
    await _seed(factory, quota_seconds=600)
    await _job(factory, "u-alice", 600, status=JobStatusEnum.DELETED)

    assert await user_get_quota_left("u-alice") is False


@pytest.mark.asyncio
async def test_failed_and_unfinished_jobs_do_not_count(factory):
    await _seed(factory, quota_seconds=600)
    await _job(factory, "u-alice", 600, status=JobStatusEnum.FAILED)
    await _job(factory, "u-alice", 600, status=JobStatusEnum.PENDING)

    assert await user_get_quota_left("u-alice") is True


@pytest.mark.asyncio
async def test_quota_resets_monthly(factory):
    await _seed(factory, quota_seconds=600)
    last_month = _now().replace(day=1) - timedelta(days=1)
    await _job(factory, "u-alice", 6000, created_at=last_month)

    assert await user_get_quota_left("u-alice") is True


@pytest.mark.asyncio
async def test_jobs_outside_the_group_do_not_count(factory):
    await _seed(factory, quota_seconds=600)
    await _job(factory, "u-loner", 6000)

    assert await user_get_quota_left("u-alice") is True


@pytest.mark.asyncio
async def test_user_without_group_is_unlimited(factory):
    await _seed(factory, quota_seconds=600)
    await _job(factory, "u-loner", 6000)

    assert await user_get_quota_left("u-loner") is True


@pytest.mark.asyncio
@pytest.mark.parametrize("quota_seconds", [0, None])
async def test_group_without_quota_is_unlimited(factory, quota_seconds):
    await _seed(factory, quota_seconds=quota_seconds)
    await _job(factory, "u-alice", 6000)

    assert await user_get_quota_left("u-alice") is True
