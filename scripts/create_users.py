#!/usr/bin/env python3
"""Create users and groups with a specific realm."""

import argparse
import string
import random
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel

from db.models import Group, GroupUserLink, User
from utils.settings import get_settings


def random_username(realm, length=8):
    prefix = "".join(random.choices(string.ascii_lowercase + string.digits, k=length))
    return f"{prefix}@{realm}"


def create_users(session, realm, count, active):
    users = []
    for _ in range(count):
        username = random_username(realm)
        user = User(
            user_id=str(uuid4()),
            username=username,
            realm=realm,
            active=active,
            transcribed_seconds=0,
        )
        session.add(user)
        users.append(user)
        print(f"Created user: {username} (realm={realm}, user_id={user.user_id})")
    return users


def create_group(session, name, realm, description=None, owner_user_id=None, quota_seconds=None):
    group = Group(
        name=name,
        realm=realm,
        description=description,
        owner_user_id=owner_user_id,
        quota_seconds=quota_seconds,
    )
    session.add(group)
    session.flush()
    print(f"Created group: {name} (realm={realm}, id={group.id})")
    return group


def add_users_to_group(session, users, group, role="member"):
    for user in users:
        session.flush()
        link = GroupUserLink(
            group_id=group.id,
            user_id=user.id,
            role=role,
            in_group=True,
        )
        session.add(link)
        print(f"Added user {user.username} to group {group.name} (role={role})")


def main():
    parser = argparse.ArgumentParser(description="Create users and groups with a specific realm")
    parser.add_argument("--realm", required=True, help="Realm for the new users/groups")
    parser.add_argument("--count", type=int, default=1, help="Number of users to create (default: 1)")
    parser.add_argument("--active", action="store_true", help="Set users as active")
    parser.add_argument("--group", help="Create a group with this name and add users to it")
    parser.add_argument("--group-description", help="Description for the group")
    parser.add_argument("--group-quota", type=int, help="Monthly quota in seconds for the group")
    parser.add_argument("--role", default="member", help="Role for users in the group (default: member)")
    args = parser.parse_args()

    settings = get_settings()
    engine = create_engine(settings.API_DATABASE_URL)
    SQLModel.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    with session_factory() as session:
        users = create_users(session, args.realm, args.count, args.active)

        if args.group:
            session.flush()
            group = create_group(
                session,
                name=args.group,
                realm=args.realm,
                description=args.group_description,
                owner_user_id=users[0].user_id if users else None,
                quota_seconds=args.group_quota,
            )
            add_users_to_group(session, users, group, role=args.role)

        session.commit()

    print(f"\nDone. Created {args.count} user(s) in realm '{args.realm}'.", end="")
    if args.group:
        print(f" Added to group '{args.group}'.", end="")
    print()


if __name__ == "__main__":
    main()
