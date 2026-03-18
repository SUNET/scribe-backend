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
#

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from db.announcement import (
    announcement_create as announcement_create_db,
    announcement_get_all,
    announcement_update as announcement_update_db,
    announcement_delete as announcement_delete_db,
)

from utils.log import get_logger

from auth.oidc import get_current_admin_user

from utils.validators import (
    CreateAnnouncementRequest,
    UpdateAnnouncementRequest,
)

log = get_logger()
router = APIRouter(tags=["admin"])


@router.get("/admin/announcements", include_in_schema=False)
async def list_announcements(
    request: Request,
    admin_user: dict = Depends(get_current_admin_user),
) -> JSONResponse:
    """
    List all announcements. BOFH only.

    Parameters:
        request (Request): The incoming HTTP request.
        admin_user (dict): The current user.

    Returns:
        JSONResponse: The list of announcements.
    """

    if not admin_user.get("bofh"):
        return JSONResponse(content={"error": "User not authorized"}, status_code=403)

    return JSONResponse(content={"result": announcement_get_all()})


@router.post("/admin/announcements", include_in_schema=False)
async def create_announcement(
    request: Request,
    announcement: CreateAnnouncementRequest,
    admin_user: dict = Depends(get_current_admin_user),
) -> JSONResponse:
    """
    Create a new announcement. BOFH only.

    Parameters:
        request (Request): The incoming HTTP request.
        announcement (CreateAnnouncementRequest): The announcement data.
        admin_user (dict): The current user.

    Returns:
        JSONResponse: The result of the operation.
    """

    if not admin_user.get("bofh"):
        return JSONResponse(content={"error": "User not authorized"}, status_code=403)

    if not announcement.message:
        return JSONResponse(content={"error": "Message is required"}, status_code=400)

    created = announcement_create_db(
        message=announcement.message,
        severity=announcement.severity,
        starts_at=announcement.starts_at,
        ends_at=announcement.ends_at,
        enabled=announcement.enabled,
        created_by=admin_user.get("username"),
    )

    return JSONResponse(content={"result": created})


@router.put("/admin/announcements/{announcement_id}", include_in_schema=False)
async def update_announcement(
    request: Request,
    announcement_id: int,
    announcement_update: UpdateAnnouncementRequest,
    admin_user: dict = Depends(get_current_admin_user),
) -> JSONResponse:
    """
    Update an announcement. BOFH only.

    Parameters:
        request (Request): The incoming HTTP request.
        announcement_id (int): The ID of the announcement to update.
        announcement_update (UpdateAnnouncementRequest): The announcement update data.
        admin_user (dict): The current user.

    Returns:
        JSONResponse: The result of the operation.
    """

    if not admin_user.get("bofh"):
        return JSONResponse(content={"error": "User not authorized"}, status_code=403)

    updated = announcement_update_db(
        announcement_id,
        message=announcement_update.message,
        severity=announcement_update.severity,
        starts_at=announcement_update.starts_at,
        ends_at=announcement_update.ends_at,
        enabled=announcement_update.enabled,
    )

    if not updated:
        return JSONResponse(
            content={"error": "Announcement not found"}, status_code=404
        )

    return JSONResponse(content={"result": updated})


@router.delete("/admin/announcements/{announcement_id}", include_in_schema=False)
async def delete_announcement(
    request: Request,
    announcement_id: int,
    admin_user: dict = Depends(get_current_admin_user),
) -> JSONResponse:
    """
    Delete an announcement. BOFH only.

    Parameters:
        request (Request): The incoming HTTP request.
        announcement_id (int): The ID of the announcement to delete.
        admin_user (dict): The current user.

    Returns:
        JSONResponse: The result of the operation.
    """

    if not admin_user.get("bofh"):
        return JSONResponse(content={"error": "User not authorized"}, status_code=403)

    if not announcement_delete_db(announcement_id):
        return JSONResponse(
            content={"error": "Announcement not found"}, status_code=404
        )

    return JSONResponse(content={"result": {"status": "OK"}})
