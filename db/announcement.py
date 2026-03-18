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

from db.models import Announcement
from db.session import get_session
from utils.log import get_logger

log = get_logger()


def announcement_create(
    message: str,
    severity: Optional[str] = "info",
    starts_at: Optional[str] = None,
    ends_at: Optional[str] = None,
    enabled: bool = True,
    created_by: Optional[str] = None,
) -> dict | None:
    """Create a new announcement."""

    with get_session() as session:
        announcement = Announcement(
            message=message,
            severity=severity or "info",
            starts_at=datetime.fromisoformat(starts_at) if starts_at else None,
            ends_at=datetime.fromisoformat(ends_at) if ends_at else None,
            enabled=enabled,
            created_by=created_by,
        )
        session.add(announcement)
        session.flush()
        return announcement.as_dict()


def announcement_get(announcement_id: int) -> dict | None:
    """Get a single announcement by ID."""

    with get_session() as session:
        announcement = session.get(Announcement, announcement_id)
        if not announcement:
            return None
        return announcement.as_dict()


def announcement_get_all() -> list[dict]:
    """Get all announcements ordered by creation date descending."""

    with get_session() as session:
        announcements = (
            session.query(Announcement)
            .order_by(Announcement.created_at.desc())
            .all()
        )
        return [a.as_dict() for a in announcements]


def announcement_update(
    announcement_id: int,
    message: Optional[str] = None,
    severity: Optional[str] = None,
    starts_at: Optional[str] = None,
    ends_at: Optional[str] = None,
    enabled: Optional[bool] = None,
) -> dict | None:
    """Update an existing announcement."""

    with get_session() as session:
        announcement = session.get(Announcement, announcement_id)
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

        session.flush()
        return announcement.as_dict()


def announcement_delete(announcement_id: int) -> bool:
    """Delete an announcement."""

    with get_session() as session:
        announcement = session.get(Announcement, announcement_id)
        if not announcement:
            return False
        session.delete(announcement)
        return True


def announcement_get_active() -> list[dict]:
    """Get all currently active announcements (enabled + within date window)."""

    now = datetime.now()

    with get_session() as session:
        query = session.query(Announcement).filter(Announcement.enabled.is_(True))

        announcements = query.all()
        active = []
        for a in announcements:
            if a.starts_at and a.starts_at > now:
                continue
            if a.ends_at and a.ends_at < now:
                continue
            active.append(a.as_dict())

        return active
