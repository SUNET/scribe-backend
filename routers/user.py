from auth.oidc import get_current_user
from db.user import (
    user_get_email,
    user_get_private_key,
    user_update,
)

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from utils.log import get_logger
from utils.notifications import notifications
from utils.settings import get_settings
from utils.crypto import validate_private_key_password
from utils.validators import UserUpdateRequest

log = get_logger()
router = APIRouter(tags=["user"])
settings = get_settings()

api_file_storage_dir = settings.API_FILE_STORAGE_DIR


@router.get("/me")
async def get_user_info(
    request: Request,
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    """
    Get user information.
    Used by the frontend to get user information.

    Parameters:
        request (Request): The incoming HTTP request.
        user (dict): The current user.

    Returns:
        JSONResponse: The user information.
    """

    return JSONResponse(content={"result": user})


@router.put("/me")
async def set_user_info(
    item: UserUpdateRequest,
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    """
    Set user information.
    Used by the frontend to set user information.

    Parameters:
        item (UserUpdateRequest): The user update data.
        user (dict): The current user.

    Returns:
        JSONResponse:  The result of the operation.
    """

    if item.encryption and item.encryption_password:
        user_update(
            user["user_id"],
            encryption_settings=item.encryption,
            encryption_password=item.encryption_password,
        )
    elif item.reset_password:
        user_update(user["user_id"], reset_encryption=True)
    elif item.verify_password:
        private_key = user_get_private_key(user["user_id"])

        try:
            validate_private_key_password(private_key, item.encryption_password)
        except ValueError:
            log.info(
                f"Invalid private key password for user {user["user_id"]}"
            )
            return JSONResponse(
                content={"error": "Invalid private key or password"},
                status_code=403,
            )
    elif item.email is not None:
        user_update(user["user_id"], email=item.email)
    elif item.notifications:
        notifications_str = ""

        if (
            item.notifications.notify_on_job is not None
            and item.notifications.notify_on_job
        ):
            notifications_str += "job,"
        if (
            item.notifications.notify_on_deletion is not None
            and item.notifications.notify_on_deletion
        ):
            notifications_str += "deletion,"
        if (
            item.notifications.notify_on_user is not None
            and item.notifications.notify_on_user
        ):
            notifications_str += "user,"
        if (
            item.notifications.notify_on_quota is not None
            and item.notifications.notify_on_quota
        ):
            notifications_str += "quota,"
        if (
            item.notifications.notify_on_weekly_report is not None
            and item.notifications.notify_on_weekly_report
        ):
            notifications_str += "weekly_report,"

        user_update(user["user_id"], notifications_str=notifications_str)

    return JSONResponse(content={"result": {"status": "OK"}})


@router.post("/me/test-notifications")
async def test_notifications(
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    """
    Temporary endpoint to test all email notification types.
    Sends one of each notification type to the current user's email.

    Parameters:
        user (dict): The current user.

    Returns:
        JSONResponse: The result of the operation.
    """

    email = user_get_email(user["user_id"])

    if not email:
        return JSONResponse(
            content={"error": "No email address configured"},
            status_code=400,
        )

    username = user.get("username", "testuser")

    notifications.send_email_verification(to_email=email)
    notifications.send_transcription_finished(to_email=email)
    notifications.send_transcription_failed(to_email=email)
    notifications.send_job_deleted(to_email=email)
    notifications.send_job_to_be_deleted(to_email=email)
    notifications.send_new_user_created(to_email=email, username=username)
    notifications.notification_send_account_activated(to_email=email)
    notifications.send_quota_alert(
        to_email=email,
        customer_name="Test Customer",
        usage_percent=96,
        blocks_purchased=10,
        minutes_included=40000,
        minutes_consumed=38400,
        remaining_minutes=1600,
    )
    notifications.send_group_quota_alert(
        to_email=email,
        group_name="Test Group",
        usage_percent=97,
        quota_minutes=5000,
        used_minutes=4850,
        remaining_minutes=150,
    )
    notifications.send_weekly_usage_report(
        to_email=email,
        customer_name="Test Customer",
        total_users=25,
        transcribed_files=142,
        transcribed_minutes=8500,
        transcribed_minutes_external=1200,
        blocks_purchased=10,
        blocks_consumed=2.13,
        minutes_included=40000,
        remaining_minutes=31500,
        overage_minutes=0,
    )

    log.info(f"Test notifications queued for {email}")

    return JSONResponse(
        content={"result": {"status": "OK", "sent_to": email, "count": 10}}
    )
