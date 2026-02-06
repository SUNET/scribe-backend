import calendar

from datetime import datetime, timedelta
from typing import Optional

from auth.client import dn_in_list
from utils.log import get_logger

from db.job import job_get_all, job_remove
from db.models import Customer, Group, GroupUserLink, Job, User
from db.session import get_session
from utils.crypto import (
    generate_rsa_keypair,
    serialize_private_key_to_pem,
    serialize_public_key_to_pem,
)
from utils.notifications import notifications
from utils.settings import get_settings

settings = get_settings()
log = get_logger()


def user_create(
    username: str,
    realm: str,
    user_id: Optional[str] = None,
    email: Optional[str] = None,
) -> dict:
    """
    Create a new user in the database.

    Parameters:
        username (str): The username of the user.
        realm (str): The realm/domain of the user.
        user_id (Optional[str]): The unique identifier of the user.

    Returns:
        dict: The created user as a dictionary.
    """

    if not user_id or not realm:
        raise ValueError("user_id and realm must be provided")

    with get_session() as session:
        user = (
            session.query(User)
            .filter((User.user_id == user_id) | (User.username == username))
            .first()
        )

        if user:
            if email != "" and user.email == "":
                user.email = email

            user.last_login = datetime.utcnow()

            return user.as_dict()

        user = User(
            username=username,
            realm=realm,
            user_id=user_id,
            transcribed_seconds="0",
            last_login=datetime.utcnow(),
            email=email,
        )

        log.info(f"User {username} created with realm {realm}.")

        session.add(user)

        # Figure out which users we should send a notification
        # email to about the new user creation.
        admins = users_admin_domains_from_realm(realm)

        for admin in admins:
            if not admin["admin"]:
                continue

            if admin_email := user_get_notifications(admin["user_id"], "user"):
                if notifications.notification_sent_record_exists(
                    admin["user_id"], user.user_id, "user_creation"
                ):
                    continue

                notifications.send_new_user_created(admin_email, username)
                notifications.notification_sent_record_add(
                    admin["user_id"], user.user_id, "user_creation"
                )
                log.info(f"Sent new user creation notification to admin {admin_email}")

        return user.dict()


def user_exists(username: str) -> bool:
    """
    Check if a user exists by user_id.

    Parameters:
        username (str): The username of the user.

    Returns:
        bool: True if the user exists, False otherwise.
    """
    with get_session() as session:
        user = session.query(User).filter(User.username == username).first()

        return user is not None


def user_get_from_job(job_id: str) -> Optional[User]:
    """
    Get a user by job_user_id.

    Parameters:
        job_id (str): The job ID.

    Returns:
        Optional[User]: The user associated with the job, or None if not found.
    """
    with get_session() as session:
        if not (job := session.query(Job).filter(Job.uuid == job_id).first()):
            return None

        user = session.query(User).filter(User.user_id == job.user_id).first()

        if user is None and dn_in_list(job.user_id):
            return job.user_id

        return user.as_dict()["user_id"] if user else None


def user_get_username_from_job(job_id: str) -> Optional[User]:
    """
    Get a user by job_user_id.

    Parameters:
        job_id (str): The job ID.

    Returns:
        Optional[User]: The user associated with the job, or None if not found.
    """
    with get_session() as session:
        if not (job := session.query(Job).filter(Job.uuid == job_id).first()):
            return None

        user = session.query(User).filter(User.user_id == job.user_id).first()

        return user.as_dict()["username"] if user else None


def user_get(
    user_id: Optional[str] = "", username: Optional[str] = ""
) -> Optional[User]:
    """
    Get a user by user_id.

    Parameters:
        user_id (Optional[str]): The user ID.
        username (Optional[str]): The username.

    Returns:
        Optional[User]: The user associated with the user_id, or None if not found.
    """

    if not user_id and not username:
        return {}

    with get_session() as session:
        if user_id:
            user = session.query(User).filter(User.user_id == user_id).first()
        else:
            user = session.query(User).filter(User.username == username).first()

        return user.as_dict()


def user_get_private_key(user_id: str) -> Optional[str]:
    """
    Get a users private key.

    Parameters:
        user_id (str): The user ID.

    Returns:
        Optional[str]: The user's private key, or None if not found.
    """
    log.info(f"Fetching private key for user {user_id}")

    return user_get(user_id)["private_key"].encode("utf-8")


def user_get_public_key(user_id: str) -> Optional[str]:
    """
    Get a users public key.

    Parameters:
        user_id (str): The user ID.

    Returns:
        Optional[str]: The user's public key, or None if not found.
    """

    return user_get(user_id)["public_key"].encode("utf-8")


def user_get_all(realm) -> list:
    """
    Get all users in a realm.

    Parameters:
        realm (str): The realm/domain to filter users by. Use "*" to get all users.

    Returns:
        list: A list of users in the specified realm.
    """
    with get_session() as session:
        if realm == "*":
            q = (
                session.query(User, Group)
                .outerjoin(GroupUserLink, GroupUserLink.user_id == User.id)
                .outerjoin(Group, Group.id == GroupUserLink.group_id)
            )
            rows = q.all()

        else:
            q = (
                session.query(User, Group)
                .outerjoin(GroupUserLink, GroupUserLink.user_id == User.id)
                .outerjoin(Group, Group.id == GroupUserLink.group_id)
                .filter(User.realm == realm)
            )
            rows = q.all()

        group_map = {}

        for row in rows:
            user_dict = row[0].as_dict()
            group_dict = row[1].as_dict() if row[1] else []

            if user_dict["username"] == "api_user":
                continue
            elif user_dict["username"].isdigit():
                customer = (
                    session.query(Customer)
                    .filter(Customer.partner_id == user_dict["username"])
                    .first()
                )

                if customer:
                    user_dict["username"] = "(REACH) " + customer.name

            if user_dict["id"] in group_map:
                group_map[user_dict["id"]]["groups"] += ", " + group_dict["name"]
            else:
                group_map[user_dict["id"]] = user_dict
                group_map[user_dict["id"]]["groups"] = (
                    group_dict["name"] if group_dict else ""
                )

        result = list(group_map.values())

        return result


def user_get_quota_left(user_id: str) -> bool:
    """
    Get the transcription quota left for a user.

    Parameters:
        user_id (str): The user ID.

    Returns:
        bool: True if the user has quota left, False otherwise.
    """

    with get_session() as session:
        groups = (
            session.query(Group).filter(Group.users.any(User.user_id == user_id)).all()
        )

        if not groups:
            return True

        for group in groups:
            if group.quota_seconds == 0:
                return True

            group_statistics_res = group_statistics(group.id, user_id, group.realm)

            if not group_statistics_res:
                return True

            if "total_transcribed_minutes" not in group_statistics_res:
                return True

            if (
                group_statistics_res["total_transcribed_minutes"]
                < group.quota_seconds / 60
            ):
                return True

    return False


def user_update(
    user_id: str,
    transcribed_seconds: Optional[str] = "",
    active: Optional[bool] = None,
    admin: Optional[bool] = None,
    admin_domains: Optional[str] = None,
    encryption_settings: Optional[bool] = None,
    encryption_password: Optional[str] = None,
    reset_encryption: Optional[bool] = False,
    notifications_str: Optional[str] = None,
    email: Optional[str] = None,
) -> dict:
    """
    Update a user in the database.

    Parameters:
        user_id (str): The user ID.
        transcribed_seconds (Optional[str]): The number of transcribed seconds to add.
        active (Optional[bool]): The active status to set.
        admin (Optional[bool]): The admin status to set.
        admin_domains (Optional[str]): The admin domains to set.
        encryption_settings (Optional[bool]): Whether to enable encryption settings.
        encryption_password (Optional[str]): The password for encryption.
        reset_encryption (Optional[bool]): Whether to reset encryption settings.

    Returns:
        dict: The updated user as a dictionary.
    """

    with get_session() as session:
        user = (
            session.query(User)
            .filter(User.user_id == user_id)
            .with_for_update()
            .first()
        )

        if not user:
            return {}

        user.last_login = datetime.utcnow()

        if transcribed_seconds:
            user.transcribed_seconds += float(transcribed_seconds)

        if active is not None:
            log.info(f"Setting user {user.user_id} active status to {active}")
            user.active = active

            if (
                user.email != ""
                and user.email is not None
                and user.active
                and not notifications.notification_sent_record_exists(
                    user.user_id, user.user_id, "account_activated"
                )
            ):
                notifications.notification_send_account_activated(user.email)
                notifications.notification_sent_record_add(
                    user.user_id, user.user_id, "account_activated"
                )

        if admin is not None:
            log.info(f"Setting user {user.user_id} admin status to {admin}")
            user.admin = admin

        if admin_domains is not None:
            log.info(f"Setting user {user.user_id} admin domains to {admin_domains}")
            user.admin_domains = admin_domains

        if encryption_settings and encryption_password != "":
            log.info(f"Updating encryption settings for user {user.user_id}")

            user.encryption_settings = True

            # Generate RSA key pair
            private_key, public_key = generate_rsa_keypair(
                key_size=settings.CRYPTO_KEY_SIZE
            )

            # Serialize keys to PEM format
            serialized_private_key = serialize_private_key_to_pem(
                private_key, encryption_password.encode("utf-8")
            )
            serialized_public_key = serialize_public_key_to_pem(public_key)

            # Store keys as UTF-8 strings
            user.private_key = serialized_private_key.decode("utf-8")
            user.public_key = serialized_public_key.decode("utf-8")

        if reset_encryption:
            # Wipe the keys and disable encryption
            log.info(f"Resetting encryption settings for user {user.user_id}")

            user.encryption_settings = False
            user.private_key = None
            user.public_key = None

            # Remove all files encrypted with the previous key
            jobs = session.query(Job).filter(Job.user_id == user.user_id).all()

            for job in jobs:
                job_remove(job.uuid)

        if email:
            log.info(f"Updating email for user {user.user_id} to {email}")
            user.email = email

            if email != "" and email is not None:
                notifications.send_email_verification(email)

        if notifications_str is not None:
            log.info(
                f"Updating notifications for user {user.user_id} to {notifications_str}"
            )
            user.notifications = notifications_str

        log.info(
            f"User {user.user_id} updated: "
            + f"transcribed_seconds={user.transcribed_seconds}, "
            + f"active={user.active}, admin={user.admin}",
        )

        return user.as_dict() if user else {}


def user_get_email(user_id: str) -> Optional[str]:
    """
    Get a user's email by user_id.

    Parameters:
        user_id (str): The user ID.

    Returns:
        Optional[str]: The email associated with the user_id, or None if not found.
    """

    with get_session() as session:
        user = session.query(User).filter(User.user_id == user_id).first()

        return user.email if user else None


def get_username_from_id(user_id: str) -> Optional[str]:
    """
    Get a username by user_id.

    Parameters:
        user_id (str): The user ID.

    Returns:
        Optional[str]: The username associated with the user_id, or None if not found.
    """

    with get_session() as session:
        user = session.query(User).filter(User.user_id == user_id).first()

    return user.username if user else None


def users_statistics(
    group_id: Optional[str] = "",
    realm: Optional[str] = "",
    days: Optional[int] = 30,
    user_id: Optional[str] = "",
) -> dict:
    """
    Get user statistics for the last 'days' days.
    Shows customer names instead of usernames when available.

    Parameters:
        group_id (Optional[str]): The group ID to filter users by.
        realm (Optional[str]): The realm/domain to filter users by.
        days (Optional[int]): The number of days to look back for statistics.
        user_id (Optional[str]): The user ID of the requesting user.

    Returns:
        dict: A dictionary containing user statistics.
    """

    with get_session() as session:
        user = session.query(User).filter(User.user_id == user_id).first()
        user_domains = (
            user.admin_domains.split(",") if user and user.admin_domains else []
        )

        if group_id == "0":
            if realm == "*":
                users = session.query(User).all()
            else:
                users = session.query(User).filter(User.realm.in_(user_domains)).all()
        else:
            if realm == "*":
                group = session.query(Group).filter(Group.id == group_id).first()
            else:
                group = session.query(Group).filter(Group.id == group_id).first()

            if not group:
                return {
                    "total_users": 0,
                    "active_users": [],
                    "transcribed_files": 0,
                    "transcribed_files_last_month": 0,
                    "total_transcribed_minutes": 0,
                    "total_transcribed_minutes_last_month": 0,
                    "transcribed_minutes_per_day": {},
                    "transcribed_minutes_per_day_previous_month": {},
                    "transcribed_minutes_per_user": {},
                    "job_queue": {},
                }

            users = group.users

        total_transcribed_minutes = 0
        total_transcribed_minutes_last_month = 0

        transcribed_files = 0
        transcribed_files_last_month = 0

        transcribed_minutes_per_user = {}
        transcribed_minutes_per_user_last_month = {}

        transcribed_minutes_per_day = {}
        transcribed_minutes_per_day_last_month = {}

        job_queue = []

        today = datetime.utcnow().date()
        last_day = calendar.monthrange(today.year, today.month)[1]
        last_date_string = f"{today.year}-{today.month:02d}-{last_day}"
        last_date = datetime.fromisoformat(last_date_string).date()
        start_date = today.replace(day=1)

        date_range = [
            (start_date + timedelta(days=i)).isoformat()
            for i in range((last_date - start_date).days + 1)
        ]

        first_day_this_month = today.replace(day=1)
        last_day_prev_month = first_day_this_month - timedelta(days=1)
        first_day_prev_month = last_day_prev_month.replace(day=1)

        num_days_prev_month = last_day_prev_month.day

        date_range_prev_month = [
            (first_day_prev_month + timedelta(days=i)).isoformat()
            for i in range(num_days_prev_month)
        ]

        transcribed_minutes_per_day = {d: 0 for d in date_range}
        transcribed_minutes_per_day_last_month = {d: 0 for d in date_range_prev_month}

        for user in users:
            jobs = job_get_all(user.user_id, cleaned=True)["jobs"]

            if not jobs:
                continue

            if user.username.isdigit():
                customer = (
                    session.query(Customer)
                    .filter(Customer.partner_id == user.username)
                    .first()
                )
                if customer:
                    display_name = "(REACH) " + customer.name
                else:
                    display_name = user.username
            else:
                display_name = user.username

            for job in jobs:
                job_date = datetime.strptime(
                    job["created_at"], "%Y-%m-%d %H:%M:%S.%f"
                ).date()

                job_date_str = job_date.isoformat()

                if job_date >= first_day_this_month:
                    if job["status"] == "completed" or job["status"] == "deleted":
                        transcribed_files += 1
                        total_transcribed_minutes += job["transcribed_seconds"] / 60

                        transcribed_minutes_per_day[job_date_str] += (
                            job["transcribed_seconds"] / 60
                        )

                        if display_name not in transcribed_minutes_per_user:
                            transcribed_minutes_per_user[display_name] = 0

                        transcribed_minutes_per_user[display_name] += (
                            job["transcribed_seconds"] / 60
                        )

                    if job["status"] == "uploaded" or job["status"] == "in_progress":
                        if job["status"] == "in_progress":
                            status = "transcribing"
                        else:
                            status = job["status"]

                        job_data = {
                            "status": status,
                            "created_at": job["created_at"],
                            "updated_at": job["updated_at"],
                            "job_id": job["uuid"],
                            "username": display_name,  # Use display name
                        }

                        job_queue.append(job_data)
                elif first_day_prev_month <= job_date <= last_day_prev_month:
                    if job["status"] == "completed" or job["status"] == "deleted":
                        transcribed_files_last_month += 1

                        total_transcribed_minutes_last_month += (
                            job["transcribed_seconds"] / 60
                        )

                        transcribed_minutes_per_day_last_month[job_date_str] += (
                            job["transcribed_seconds"] / 60
                        )

                        if display_name not in transcribed_minutes_per_user_last_month:
                            transcribed_minutes_per_user_last_month[display_name] = 0

                        transcribed_minutes_per_user_last_month[display_name] += (
                            job["transcribed_seconds"] / 60
                        )

                    if job["status"] == "uploaded" or job["status"] == "in_progress":
                        if job["status"] == "in_progress":
                            status = "transcribing"
                        else:
                            status = job["status"]

                        job_data = {
                            "status": status,
                            "created_at": job["created_at"],
                            "updated_at": job["updated_at"],
                            "job_id": job["uuid"],
                            "username": display_name,  # Use display name
                        }

                        job_queue.append(job_data)
                else:
                    log.debug(
                        f"Skipping job {job['uuid']} for user {user.username}"
                        + f" with date {job_date_str}"
                    )

        return {
            "total_users": len(users),
            "active_users": [user.as_dict() for user in users],
            "transcribed_files": int(transcribed_files),
            "transcribed_files_last_month": int(transcribed_files_last_month),
            "total_transcribed_minutes": float(total_transcribed_minutes),
            "total_transcribed_minutes_last_month": float(
                total_transcribed_minutes_last_month
            ),
            "transcribed_minutes_per_day": transcribed_minutes_per_day,
            "transcribed_minutes_per_day_last_month": transcribed_minutes_per_day_last_month,
            "transcribed_minutes_per_user": transcribed_minutes_per_user,
            "transcribed_minutes_per_user_last_month": transcribed_minutes_per_user_last_month,
            "job_queue": job_queue,
        }


def group_statistics(group_id: str, user_id: str, realm: str) -> dict:
    """
    Get group statistics for a user.

    Parameters:
        group_id (str): The group ID.
        user_id (str): The user ID of the requesting user.
        realm (str): The realm/domain to filter users by.

    Returns:
        dict: A dictionary containing group statistics.
    """

    stats = users_statistics(group_id=group_id, user_id=user_id, realm=realm)

    condensed_stats = {
        "total_users": stats["total_users"],
        "transcribed_files": stats["transcribed_files"],
        "transcribed_files_last_month": stats["transcribed_files_last_month"],
        "total_transcribed_minutes": stats["total_transcribed_minutes"],
        "total_transcribed_minutes_last_month": stats[
            "total_transcribed_minutes_last_month"
        ],
    }

    return condensed_stats


def user_can_transcribe(user_id: str) -> int:
    """
    Check which group a user belongs to and check whether the user have
    quota left or not.

    Parameters:
        user_id (str): The user ID.

    Returns:
        int:
            -1 if the user has unlimited quota,
            0 if the user has no quota left,
            >0 indicating the number of seconds left in the quota.
    """

    with get_session() as session:
        if not (user := session.query(User).filter(User.user_id == user_id).first()):
            return 0

        groups = (
            session.query(Group).filter(Group.users.any(User.user_id == user_id)).all()
        )

        if not groups:
            return -1

        for group in groups:
            if group.transcription_quota == 0:
                return -1  # Unlimited quota

            if user.transcribed_seconds < group.transcription_quota:
                return group.transcription_quota - user.transcribed_seconds

        return 0


def user_get_notifications(user_id: str, notification: str) -> Optional[str]:
    """
    Get a user's notification settings by user_id.

    Parameters:
        user_id (str): The user ID.

    Returns:
        Optional[str]: The email associated with the user_id if the notification
        setting is enabled, or None if not found.
    """

    with get_session() as session:
        user = session.query(User).filter(User.user_id == user_id).first()

        if not user.notifications:
            return None

        if notification in user.notifications.split(","):
            return user.email

        return None


def users_admin_domains_from_realm(realm: str) -> list:
    """
    Get all users which have the ralm in their list of admin_domains.

    Parameters:
        realm (str): The realm/domain to filter users by.

    Returns:
        list: A list of users which have the realm in their admin_domains.
    """

    with get_session() as session:
        users = session.query(User).filter(User.admin_domains.ilike(realm)).all()

        return [user.as_dict() for user in users]
