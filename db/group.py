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

from db.customer import customer_get_from_user_id
from db.models import Group, GroupModelLink, GroupUserLink, User
from db.session import get_async_session, get_session
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload
from typing import Optional

from utils.log import get_logger
from utils.notifications import notifications

log = get_logger()


# Helper to add eager loading options for Group relationships
def _group_eager_options():
    return [selectinload(Group.users), selectinload(Group.allowed_models)]


async def group_create(
    name: str,
    realm: str,
    description: Optional[str] = None,
    owner_user_id: Optional[int] = None,
    quota_seconds: Optional[int] = 0,
) -> dict:
    """
    Create a new group in the database.

    Parameters:
        name (str): The name of the group.
        realm (str): The realm/domain of the group.
        description (Optional[str]): A description of the group.
        owner_user_id (Optional[int]): The user ID of the group owner.
        quota_seconds (Optional[int]): The quota in seconds for the group.

    Returns:
        dict: The created group as a dictionary.
    """

    async with get_async_session() as session:
        group = Group(
            name=name,
            realm=realm,
            description=description,
            owner_user_id=owner_user_id,
            quota_seconds=quota_seconds,
        )

        session.add(group)
        await session.flush()

        # Refresh with eager loading for as_dict()
        await session.refresh(group, attribute_names=["users", "allowed_models"])

        log.info(f"Group {group.id} created with name {name}.")

        return group.as_dict()


async def group_get(group_id: int, realm: str, user_id: Optional[str] = "") -> Optional[dict]:
    """
    Get a group by id with its users and models.

    Parameters:
        group_id (int): The ID of the group to retrieve.
        realm (str): The realm/domain to filter users.
        user_id (Optional[str]): The user ID of the requester for permission checks.

    Returns:
        Optional[dict]: The group as a dictionary, or None if not found.
    """

    async with get_async_session() as session:
        if group_id == 0:
            # Default group with all users
            group = Group(name="All users", realm=realm)
        else:
            if realm == "*":
                # Admin requesting from all realms
                result = await session.execute(
                    select(Group)
                    .where(Group.id == group_id)
                    .options(*_group_eager_options())
                )
                group = result.scalars().first()
            else:
                # Check if user has access to the group
                admin_domains = (
                    await session.execute(
                        select(User.admin_domains).where(User.user_id == user_id)
                    )
                ).scalar()

                # If no admin domains, only allow if user is in group or is owner
                result = await session.execute(
                    select(Group)
                    .where(Group.id == group_id)
                    .where(
                        or_(
                            Group.users.any(User.user_id == user_id),
                            Group.owner_user_id == user_id,
                            Group.realm.in_(
                                [domain.strip() for domain in admin_domains.split(",")]
                                if admin_domains
                                else []
                            ),
                        )
                    )
                    .options(*_group_eager_options())
                )
                group = result.scalars().first()

        if not group:
            return {}

        if realm == "*":
            # Admin requesting from all realms
            result = await session.execute(
                select(User)
                .where(~User.groups.any(Group.id == group_id), User.deleted == False)  # noqa: E712
            )
            other_users = result.scalars().all()
        else:
            # Check admin domains for additional users
            admin_domains = (
                await session.execute(
                    select(User.admin_domains).where(User.user_id == user_id)
                )
            ).scalar()

            if not admin_domains:
                return group.as_dict()

            # Get users not in the group but in the admin domains
            result = await session.execute(
                select(User)
                .where(
                    ~User.groups.any(Group.id == group_id),
                    User.deleted == False,  # noqa: E712
                    User.realm.in_(
                        [domain.strip() for domain in admin_domains.split(",")]
                    ),
                )
            )
            other_users = result.scalars().all()

        group_dict = group.as_dict()

        for user in group_dict["users"]:
            user["in_group"] = True

        if other_users:
            for other in other_users:
                user_dict = other.as_dict()
                user_dict["in_group"] = False
                group_dict["users"].append(user_dict)

        return group_dict


async def group_get_from_user_id(user_id: str) -> list[dict]:
    """
    Get all groups for a specific user id.

    Parameters:
        user_id (str): The user ID to retrieve groups for.

    Returns:
        list[dict]: A list of groups the user belongs to.
    """

    async with get_async_session() as session:
        result = await session.execute(
            select(Group)
            .where(Group.users.any(User.user_id == user_id))
            .options(*_group_eager_options())
        )
        return [g.as_dict() for g in result.scalars().all()]


async def group_get_all(user_id: str, realm: str) -> list[dict]:
    """
    Get all groups with their users and models.

    Parameters:
        user_id (str): The user ID of the requester for permission checks.
        realm (str): The realm/domain to filter users.

    Returns:
        list[dict]: A list of groups with their metadata.
    """

    all_users = []
    groups_list = []

    if realm == "*":
        default_group = {
            "id": 0,
            "name": "All users",
            "realm": realm,
            "description": "Default group with all users",
            "created_at": "",
            "owner_user_id": None,
            "quota_seconds": 0,
            "users": [],
            "models": [],
            "nr_users": 0,
        }

        groups_list.append(default_group)

    async with get_async_session() as session:
        admin_domains = (
            await session.execute(
                select(User.admin_domains).where(User.user_id == user_id)
            )
        ).scalar()

        if realm == "*":
            result = await session.execute(
                select(Group).options(*_group_eager_options())
            )
            groups = result.scalars().all()
        elif admin_domains:
            domains = [
                domain.strip() for domain in admin_domains.split(",") if domain.strip()
            ]

            result = await session.execute(
                select(Group)
                .where(Group.realm.in_(domains))
                .options(*_group_eager_options())
            )
            groups = result.scalars().all()
        else:
            result = await session.execute(
                select(Group)
                .where(
                    or_(
                        Group.users.any(User.user_id == user_id),
                        Group.owner_user_id == user_id,
                    )
                )
                .options(*_group_eager_options())
            )
            groups = result.scalars().all()

        for group in groups:
            group_dict = group.as_dict()
            group_dict["nr_users"] = len(group_dict["users"])
            cust = await customer_get_from_user_id(group_dict["owner_user_id"])
            group_dict["customer_name"] = cust.get("name", "None") if cust else "None"

            groups_list.append(group_dict)
            all_users.extend(group_dict["users"])

        if realm != "*":
            group_for_all_users = {
                "id": 0,
                "name": "All users",
                "realm": realm,
                "description": "Default group with all users",
                "created_at": "",
                "owner_user_id": None,
                "quota_seconds": 0,
                "users": [],
                "nr_users": len(all_users),
                "customer_name": "",
            }

            groups_list.append(group_for_all_users)

    return groups_list


async def group_get_quota_left(group_id: int) -> int:
    """
    Get the remaining quota seconds for a group.

    Parameters:
        group_id (int): The ID of the group.

    Returns:
        int: The remaining quota seconds for the group.
    """

    async with get_async_session() as session:
        result = await session.execute(
            select(Group).where(Group.id == group_id)
        )
        group = result.scalars().first()
        if not group:
            return 0

        quota_seconds = group.quota_seconds

        used_seconds = (
            await session.execute(
                select(func.coalesce(func.sum(User.transcribed_seconds), 0))
                .join(GroupUserLink, GroupUserLink.user_id == User.id)
                .where(GroupUserLink.group_id == group_id)
            )
        ).scalar()

        return max(quota_seconds - used_seconds, 0)


async def group_delete(group_id: int) -> bool:
    """
    Delete a group by id.

    Parameters:
        group_id (int): The ID of the group to delete.

    Returns:
        bool: True if the group was deleted, False otherwise.
    """
    async with get_async_session() as session:
        result = await session.execute(
            select(Group).where(Group.id == group_id)
        )
        group = result.scalars().first()
        if not group:
            return False

        # Bulk delete all links to users and models
        await session.execute(
            select(GroupUserLink).where(GroupUserLink.group_id == group_id)
        )
        from sqlalchemy import delete
        await session.execute(
            delete(GroupUserLink).where(GroupUserLink.group_id == group_id)
        )
        await session.execute(
            delete(GroupModelLink).where(GroupModelLink.group_id == group_id)
        )

        await session.delete(group)

        log.info(f"Group {group_id} deleted.")

        return True


async def group_update(
    group_id: int,
    name: Optional[str] = None,
    description: Optional[str] = None,
    usernames: Optional[list[int]] = None,
    quota_seconds: Optional[int] = 0,
) -> Optional[dict]:
    """
    Update group metadata.

    Parameters:
        group_id (str): The ID of the group to update.
        name (Optional[str]): The new name of the group.
        description (Optional[str]): The new description of the group.
        usernames (Optional[list[int]]): List of usernames to set as group members.
        quota_seconds (Optional[int]): The new quota in seconds for the group.

    Returns:
        Optional[dict]: The updated group as a dictionary, or None if not found.
    """

    async with get_async_session() as session:
        result = await session.execute(
            select(Group)
            .where(Group.id == group_id)
            .with_for_update()
            .options(*_group_eager_options())
        )
        group = result.scalars().first()
        if not group:
            return {}

        if name is not None:
            group.name = name
        if description is not None:
            group.description = description
        if quota_seconds is not None:
            group.quota_seconds = quota_seconds
        if usernames is not None:
            # Batch-fetch all users by username in one query
            users_result = await session.execute(
                select(User).where(
                    User.username.in_(usernames), User.deleted == False  # noqa: E712
                )
            )
            users_list = users_result.scalars().all()
            users_map = {u.username: u for u in users_list}

            # Batch-check for users already in other groups
            user_db_ids = [u.id for u in users_map.values()]
            if user_db_ids:
                existing_result = await session.execute(
                    select(GroupUserLink, Group.name)
                    .join(Group, Group.id == GroupUserLink.group_id)
                    .where(
                        GroupUserLink.group_id != group.id,
                        GroupUserLink.user_id.in_(user_db_ids),
                    )
                )
                existing_links = existing_result.all()

                # Build reverse map: user db id -> username
                id_to_username = {u.id: u.username for u in users_map.values()}

                for link, group_name in existing_links:
                    username = id_to_username.get(link.user_id, "unknown")
                    raise ValueError(
                        f'User {username} is already in the group "{group_name}".'
                    )

            # Bulk delete existing links
            from sqlalchemy import delete
            await session.execute(
                delete(GroupUserLink).where(GroupUserLink.group_id == group.id)
            )

            for username in usernames:
                user = users_map.get(username)

                if user:
                    link = GroupUserLink(
                        group_id=group.id, user_id=user.id, role="member"
                    )

                    session.add(link)
        log.info(f"Group {group.id} updated.")

        return group.as_dict()


async def group_add_user(group_id: int, username: str, role: str = "member") -> dict:
    """
    Add a user to a group with a given role.

    Parameters:
        group_id (int): The ID of the group.
        username (str): The username of the user to add.
        role (str): The role of the user in the group.

    Returns:
        dict: The group-user link as a dictionary.
    """
    async with get_async_session() as session:
        result = await session.execute(
            select(User).where(
                User.username == username, User.deleted == False  # noqa: E712
            )
        )
        user = result.scalars().first()
        if not user:
            return {}

        user_id = user.id

        result = await session.execute(
            select(GroupUserLink).where(
                GroupUserLink.group_id == group_id, GroupUserLink.user_id == user_id
            )
        )
        link = result.scalars().first()
        if not link:
            link = GroupUserLink(group_id=group_id, user_id=user_id, role=role)
            session.add(link)

        log.info(f"User {user_id} added to group {group_id} with role {role}.")

        return {"group_id": group_id, "user_id": user_id, "role": role}


async def group_remove_user(group_id: int, username: str) -> bool:
    """
    Remove a user from a group.

    Parameters:
        group_id (int): The ID of the group.
        username (str): The username of the user to remove.

    Returns:
        bool: True if the user was removed, False otherwise.
    """
    async with get_async_session() as session:
        result = await session.execute(
            select(User).where(
                User.username == username, User.deleted == False  # noqa: E712
            )
        )
        user = result.scalars().first()
        if not user:
            return False

        result = await session.execute(
            select(GroupUserLink).where(
                GroupUserLink.group_id == group_id, GroupUserLink.user_id == user.id
            )
        )
        link = result.scalars().first()

        if not link:
            return False

        await session.delete(link)

        log.info(f"User {username} removed from group {group_id}.")

        return True


async def group_add_model(group_id: int, model_id: int) -> dict:
    """
    Link a model to a group.

    Parameters:
        group_id (int): The ID of the group.
        model_id (int): The ID of the model to link.

    Returns:
        dict: The group-model link as a dictionary.
    """
    async with get_async_session() as session:
        result = await session.execute(
            select(GroupModelLink).where(
                GroupModelLink.group_id == group_id, GroupModelLink.model_id == model_id
            )
        )
        link = result.scalars().first()

        if not link:
            link = GroupModelLink(group_id=group_id, model_id=model_id)
            session.add(link)

        return {"group_id": group_id, "model_id": model_id}


async def group_remove_model(group_id: int, model_id: int) -> bool:
    """
    Unlink a model from a group.

    Parameters:
        group_id (int): The ID of the group.
        model_id (int): The ID of the model to unlink.

    Returns:
        bool: True if the model was unlinked, False otherwise.
    """
    async with get_async_session() as session:
        result = await session.execute(
            select(GroupModelLink).where(
                GroupModelLink.group_id == group_id, GroupModelLink.model_id == model_id
            )
        )
        link = result.scalars().first()

        if not link:
            return False

        await session.delete(link)

        return True


async def group_list() -> list[dict]:
    """
    List all groups with their metadata.

    Returns:
        list[dict]: A list of groups as dictionaries.
    """
    async with get_async_session() as session:
        result = await session.execute(
            select(Group).options(*_group_eager_options())
        )
        return [g.as_dict() for g in result.scalars().all()]


async def group_get_users(group_id: int, realm: str) -> list[dict]:
    """
    Get all users in a group.

    Parameters:
        group_id (int): The ID of the group.
        realm (str): The realm/domain to filter users.

    Returns:
        list[dict]: A list of users in the group as dictionaries.
    """
    async with get_async_session() as session:
        result = await session.execute(
            select(Group)
            .where(Group.id == group_id, Group.realm == realm)
            .options(*_group_eager_options())
        )
        group = result.scalars().first()
        if not group:
            return []

        return [user.as_dict() for user in group.users]


def check_group_quota_alerts() -> None:
    """
    Check all groups with a quota for 95%+ consumption.
    Sends email alerts to admin users of the group's realm who have the quota notification enabled.

    Returns:
        None
    """

    with get_session() as session:
        # Fetch groups with quota and their usage in one query
        group_usage_rows = (
            session.query(
                Group,
                func.coalesce(func.sum(User.transcribed_seconds), 0).label("used_seconds"),
            )
            .outerjoin(GroupUserLink, GroupUserLink.group_id == Group.id)
            .outerjoin(User, User.id == GroupUserLink.user_id)
            .filter(Group.quota_seconds > 0)
            .group_by(Group.id)
            .all()
        )

        for group, used_seconds in group_usage_rows:
            quota_seconds = group.quota_seconds

            usage_percent = int((used_seconds / quota_seconds) * 100)

            if usage_percent < 95:
                continue

            quota_minutes = quota_seconds // 60
            used_minutes = used_seconds // 60
            remaining_minutes = max(quota_minutes - used_minutes, 0)

            admin_users = session.query(User).filter(
                User.admin == True,
                User.admin_domains.ilike(f"%{group.realm}%"),
            ).all()

            for admin_user in admin_users:
                if not admin_user.notifications or "quota" not in admin_user.notifications.split(","):
                    continue

                if not admin_user.email:
                    continue

                if notifications.notification_sent_record_exists(
                    admin_user.user_id, str(group.id), "group_quota_alert"
                ):
                    continue

                notifications.send_group_quota_alert(
                    to_email=admin_user.email,
                    group_name=group.name,
                    usage_percent=usage_percent,
                    quota_minutes=quota_minutes,
                    used_minutes=used_minutes,
                    remaining_minutes=remaining_minutes,
                )

                notifications.notification_sent_record_add(
                    admin_user.user_id, str(group.id), "group_quota_alert"
                )

                log.info(
                    f"Group quota alert sent to {admin_user.email} for group {group.name} ({usage_percent}%)"
                )
