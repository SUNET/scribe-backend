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

from datetime import datetime
from typing import Optional

from sqlalchemy import select

from db.models import Announcement
from db.session import get_async_session
from utils.log import get_logger

log = get_logger()


async def announcement_create(
    message: str,
    severity: Optional[str] = "info",
    starts_at: Optional[str] = None,
    ends_at: Optional[str] = None,
    enabled: bool = True,
    created_by: Optional[str] = None,
) -> dict | None:
    """Create a new announcement."""

    async with get_async_session() as session:
        announcement = Announcement(
            message=message,
            severity=severity or "info",
            starts_at=datetime.fromisoformat(starts_at) if starts_at else None,
            ends_at=datetime.fromisoformat(ends_at) if ends_at else None,
            enabled=enabled,
            created_by=created_by,
        )
        session.add(announcement)
        await session.flush()
        return announcement.as_dict()


async def announcement_get(announcement_id: int) -> dict | None:
    """Get a single announcement by ID."""

    async with get_async_session() as session:
        announcement = await session.get(Announcement, announcement_id)
        if not announcement:
            return None
        return announcement.as_dict()


async def announcement_get_all() -> list[dict]:
    """Get all announcements ordered by creation date descending."""

    async with get_async_session() as session:
        result = await session.execute(
            select(Announcement).order_by(Announcement.created_at.desc())
        )
        announcements = result.scalars().all()
        return [a.as_dict() for a in announcements]


async def announcement_update(
    announcement_id: int,
    message: Optional[str] = None,
    severity: Optional[str] = None,
    starts_at: Optional[str] = None,
    ends_at: Optional[str] = None,
    enabled: Optional[bool] = None,
) -> dict | None:
    """Update an existing announcement."""

    async with get_async_session() as session:
        announcement = await session.get(Announcement, announcement_id)
        if not announcement:
            return None

        if message is not None:
            announcement.message = message
        if severity is not None:
            announcement.severity = severity
        if starts_at is not None:
            announcement.starts_at = (
                datetime.fromisoformat(starts_at) if starts_at else None
            )
        if ends_at is not None:
            announcement.ends_at = (
                datetime.fromisoformat(ends_at) if ends_at else None
            )
        if enabled is not None:
            announcement.enabled = enabled

        await session.flush()
        return announcement.as_dict()


async def announcement_delete(announcement_id: int) -> bool:
    """Delete an announcement."""

    async with get_async_session() as session:
        announcement = await session.get(Announcement, announcement_id)
        if not announcement:
            return False
        session.delete(announcement)
        return True


async def announcement_get_active() -> list[dict]:
    """Get all currently active announcements (enabled + within date window)."""

    now = datetime.now()

    async with get_async_session() as session:
        result = await session.execute(
            select(Announcement).where(Announcement.enabled.is_(True))
        )

        announcements = result.scalars().all()
        active = []
        for a in announcements:
            if a.starts_at and a.starts_at > now:
                continue
            if a.ends_at and a.ends_at < now:
                continue
            active.append(a.as_dict())

        return active
