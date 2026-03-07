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
from db.models import Customer, Group, GroupModelLink, GroupUserLink, User
from db.session import get_session
from sqlalchemy import or_
from typing import Optional

from utils.log import get_logger

log = get_logger()


def group_create(
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

    with get_session() as session:
        group = Group(
            name=name,
            realm=realm,
            description=description,
            owner_user_id=owner_user_id,
            quota_seconds=quota_seconds,
        )

        session.add(group)
        session.flush()

        log.info(f"Group {group.id} created with name {name}.")

        return group.as_dict()


def group_get(group_id: str, realm: str, user_id: Optional[str] = "") -> Optional[dict]:
    """
    Get a group by id with its users and models.

    Parameters:
        group_id (str): The ID of the group to retrieve.
        realm (str): The realm/domain to filter users.
        user_id (Optional[str]): The user ID of the requester for permission checks.

    Returns:
        Optional[dict]: The group as a dictionary, or None if not found.
    """

    with get_session() as session:
        if group_id == "0":
            # Default group with all users
            group = Group(name="All users", realm=realm)
        else:
            if realm == "*":
                # Admin requesting from all realms
                group = session.query(Group).filter(Group.id == group_id).first()
            else:
                # Check if user has access to the group
                admin_domains = (
                    session.query(User.admin_domains)
                    .filter(User.user_id == user_id)
                    .scalar()
                )

                # If no admin domains, only allow if user is in group or is owner
                group = (
                    session.query(Group)
                    .filter(Group.id == group_id)
                    .filter(
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
                    .first()
                )

        if not group:
            return {}

        if realm == "*":
            # Admin requesting from all realms
            other_users = (
                session.query(User).filter(~User.groups.any(Group.id == group_id)).all()
            )
        else:
            # Check admin domains for additional users
            admin_domains = (
                session.query(User.admin_domains)
                .filter(User.user_id == user_id)
                .scalar()
            )

            if not admin_domains:
                return group.as_dict()

            # Get users not in the group but in the admin domains
            other_users = (
                session.query(User)
                .filter(~User.groups.any(Group.id == group_id))
                .filter(
                    User.realm.in_(
                        [domain.strip() for domain in admin_domains.split(",")]
                    )
                )
                .all()
            )
        group_dict = group.as_dict()

        for user in group_dict["users"]:
            user["in_group"] = True

        if other_users:
            for other in other_users:
                user_dict = other.as_dict()
                user_dict["in_group"] = False
                group_dict["users"].append(user_dict)

        return group_dict


def group_get_from_user_id(user_id: str) -> list[dict]:
    """
    Get all groups for a specific user id.

    Parameters:
        user_id (str): The user ID to retrieve groups for.

    Returns:
        list[dict]: A list of groups the user belongs to.
    """

    with get_session() as session:
        groups = (
            session.query(Group).filter(Group.users.any(User.user_id == user_id)).all()
        )

    return groups


def group_get_all(user_id: str, realm: str) -> list[dict]:
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

    with get_session() as session:
        admin_domains = (
            session.query(User.admin_domains).filter(User.user_id == user_id).scalar()
        )

        if realm == "*":
            groups = session.query(Group).all()
        elif admin_domains:
            domains = [
                domain.strip() for domain in admin_domains.split(",") if domain.strip()
            ]

            groups = session.query(Group).filter(Group.realm.in_(domains)).all()
        else:
            groups = (
                session.query(Group)
                .filter(
                    or_(
                        Group.users.any(User.user_id == user_id),
                        Group.owner_user_id == user_id,
                    )
                )
                .all()
            )

        # Batch-load customer names for all group owners
        owner_ids = [g.owner_user_id for g in groups if g.owner_user_id]
        owner_realms = {}
        if owner_ids:
            owner_users = (
                session.query(User.user_id, User.realm)
                .filter(User.user_id.in_(owner_ids))
                .all()
            )
            owner_realms = {u.user_id: u.realm for u in owner_users}

        realm_to_customer = {}
        unique_realms = set(owner_realms.values())
        if unique_realms:
            customers = (
                session.query(Customer)
                .filter(or_(*(Customer.realms.like(f"%{r}%") for r in unique_realms)))
                .all()
            )
            for c in customers:
                for r in unique_realms:
                    if r in [x.strip() for x in c.realms.split(",") if x.strip()]:
                        realm_to_customer[r] = c.name

        for group in groups:
            group_dict = group.as_dict()
            group_dict["nr_users"] = len(group_dict["users"])
            owner_realm = owner_realms.get(group_dict["owner_user_id"])
            group_dict["customer_name"] = realm_to_customer.get(owner_realm, "None")

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


def group_get_quota_left(group_id: int) -> int:
    """
    Get the remaining quota seconds for a group.

    Parameters:
        group_id (int): The ID of the group.

    Returns:
        int: The remaining quota seconds for the group.
    """

    with get_session() as session:
        if not (group := session.query(Group).filter(Group.id == group_id).first()):
            return 0

        quota_seconds = group.quota_seconds
        used_seconds = 0

        for user in group.users:
            used_seconds += user.transcribed_seconds if user.transcribed_seconds else 0

        quota_left = quota_seconds - used_seconds

        return max(quota_left, 0)


def group_delete(group_id: int) -> bool:
    """
    Delete a group by id.

    Parameters:
        group_id (int): The ID of the group to delete.

    Returns:
        bool: True if the group was deleted, False otherwise.
    """
    with get_session() as session:
        if not (group := session.query(Group).filter(Group.id == group_id).first()):
            return False

        session.delete(group)

        # Also delete all links to users and models
        links = (
            session.query(GroupUserLink)
            .filter(GroupUserLink.group_id == group_id)
            .all()
        )

        if links:
            for link in links:
                session.delete(link)

        links = (
            session.query(GroupModelLink)
            .filter(GroupModelLink.group_id == group_id)
            .all()
        )

        if links:
            for link in links:
                session.delete(link)

        log.info(f"Group {group_id} deleted.")

        return True

    return False


def group_update(
    group_id: str,
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

    with get_session() as session:
        if not (
            group := session.query(Group)
            .filter(Group.id == group_id)
            .with_for_update()
            .first()
        ):
            return {}

        if name is not None:
            group.name = name
        if description is not None:
            group.description = description
        if quota_seconds is not None:
            group.quota_seconds = quota_seconds
        if usernames is not None:
            # Batch-load all users by username
            users = (
                session.query(User)
                .filter(User.username.in_(usernames))
                .all()
            )
            user_by_name = {u.username: u for u in users}
            user_ids = [u.id for u in users]

            # Batch-check if any of these users are in other groups
            if user_ids:
                conflicts = (
                    session.query(GroupUserLink, Group.name)
                    .join(Group, Group.id == GroupUserLink.group_id)
                    .filter(
                        GroupUserLink.group_id != group.id,
                        GroupUserLink.user_id.in_(user_ids),
                    )
                    .all()
                )

                if conflicts:
                    # Find the username for the conflicting user
                    conflict_user_ids = {c[0].user_id: c[1] for c in conflicts}
                    for username in usernames:
                        user = user_by_name.get(username)
                        if user and user.id in conflict_user_ids:
                            raise ValueError(
                                f'User {username} is already in the group "{conflict_user_ids[user.id]}".'
                            )

            links = (
                session.query(GroupUserLink)
                .filter(GroupUserLink.group_id == group.id)
                .all()
            )

            if links:
                for link in links:
                    session.delete(link)

            for username in usernames:
                user = user_by_name.get(username)

                if user:
                    link = GroupUserLink(
                        group_id=group.id, user_id=user.id, role="member"
                    )

                    session.add(link)
        log.info(f"Group {group.id} updated.")

        return group.as_dict()


def group_add_user(group_id: int, username: str, role: str = "member") -> dict:
    """
    Add a user to a group with a given role.

    Parameters:
        group_id (int): The ID of the group.
        username (str): The username of the user to add.
        role (str): The role of the user in the group.

    Returns:
        dict: The group-user link as a dictionary.
    """
    with get_session() as session:
        user_id = session.query(User.id).filter(User.username == username).scalar()

        link = (
            session.query(GroupUserLink)
            .filter(
                GroupUserLink.group_id == group_id, GroupUserLink.user_id == user_id
            )
            .first()
        )
        if not link:
            link = GroupUserLink(group_id=group_id, user_id=user_id, role=role)
            session.add(link)

        log.info(f"User {username} added to group {group_id} with role {role}.")

        return {"group_id": group_id, "user_id": user_id, "role": role}


def group_remove_user(group_id: int, user_id: int) -> bool:
    """
    Remove a user from a group.

    Parameters:
        group_id (int): The ID of the group.
        user_id (int): The ID of the user to remove.

    Returns:
        bool: True if the user was removed, False otherwise.
    """
    with get_session() as session:
        link = (
            session.query(GroupUserLink)
            .filter(
                GroupUserLink.group_id == group_id, GroupUserLink.user_id == user_id
            )
            .first()
        )

        if not link:
            return False

        session.delete(link)

        log.info(f"User {user_id} removed from group {group_id}.")

        return True


def group_add_model(group_id: int, model_id: int) -> dict:
    """
    Link a model to a group.

    Parameters:
        group_id (int): The ID of the group.
        model_id (int): The ID of the model to link.

    Returns:
        dict: The group-model link as a dictionary.
    """
    with get_session() as session:
        link = (
            session.query(GroupModelLink)
            .filter(
                GroupModelLink.group_id == group_id, GroupModelLink.model_id == model_id
            )
            .first()
        )

        if not link:
            link = GroupModelLink(group_id=group_id, model_id=model_id)
            session.add(link)

        return {"group_id": group_id, "model_id": model_id}


def group_remove_model(group_id: int, model_id: int) -> bool:
    """
    Unlink a model from a group.

    Parameters:
        group_id (int): The ID of the group.
        model_id (int): The ID of the model to unlink.

    Returns:
        bool: True if the model was unlinked, False otherwise.
    """
    with get_session() as session:
        link = (
            session.query(GroupModelLink)
            .filter(
                GroupModelLink.group_id == group_id, GroupModelLink.model_id == model_id
            )
            .first()
        )

        if not link:
            return False

        session.delete(link)

        return True


def group_list() -> list[dict]:
    """
    List all groups with their metadata.

    Returns:
        list[dict]: A list of groups as dictionaries.
    """
    with get_session() as session:
        return [g.as_dict() for g in session.query(Group).all()]


def group_get_users(group_id: str, realm: str) -> list[dict]:
    """
    Get all users in a group.

    Parameters:
        group_id (str): The ID of the group.
        realm (str): The realm/domain to filter users.

    Returns:
        list[dict]: A list of users in the group as dictionaries.
    """
    with get_session() as session:
        if not (
            group := (
                session.query(Group)
                .filter(Group.id == group_id)
                .filter(Group.realm == realm)
                .first()
            )
        ):
            return []

        return [user.as_dict() for user in group.users]
