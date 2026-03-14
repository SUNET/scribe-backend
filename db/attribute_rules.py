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

import re

from typing import Optional

from db.group import group_add_user
from db.models import AttributeConditionEnum, AttributeRule, Group, User
from db.session import get_session
from utils.log import get_logger

log = get_logger()


def rule_create(
    name: str,
    attribute_name: str,
    attribute_condition: str,
    attribute_value: str,
    realm: Optional[str] = None,
    activate: bool = False,
    admin: bool = False,
    deny: bool = False,
    assign_to_group: Optional[str] = None,
    owner_domains: Optional[str] = None,
    enabled: bool = True,
) -> dict:
    """Create a new attribute rule."""

    with get_session() as session:
        rule = AttributeRule(
            name=name,
            attribute_name=attribute_name,
            attribute_condition=AttributeConditionEnum(attribute_condition),
            attribute_value=attribute_value,
            realm=realm,
            activate=activate,
            admin=admin,
            deny=deny,
            assign_to_group=assign_to_group,
            owner_domains=owner_domains,
            enabled=enabled,
        )
        session.add(rule)
        session.flush()
        log.info(f"Attribute rule '{name}' created (id={rule.id}).")
        return rule.as_dict()


def rule_get(rule_id: int) -> Optional[dict]:
    """Get a single attribute rule by ID."""

    with get_session() as session:
        rule = session.query(AttributeRule).filter(AttributeRule.id == rule_id).first()
        return rule.as_dict() if rule else None


def rule_get_all(realm: Optional[str | list[str]] = None) -> list[dict]:
    """Get all attribute rules, optionally filtered by realm(s).

    For comma-separated realm values in rules, checks if any of the
    rule's realms overlap with the requested realm(s).
    """

    with get_session() as session:
        rules = session.query(AttributeRule).order_by(AttributeRule.id).all()
        all_rules = [r.as_dict() for r in rules]

    if not realm or realm == "*":
        return all_rules

    allowed = set(realm) if isinstance(realm, list) else {realm}
    result = []
    for r in all_rules:
        if not r.get("realm"):
            result.append(r)
            continue
        rule_realms = {x.strip() for x in r["realm"].split(",") if x.strip()}
        if rule_realms & allowed:
            result.append(r)
    return result


def rule_update(
    rule_id: int,
    name: Optional[str] = None,
    attribute_name: Optional[str] = None,
    attribute_condition: Optional[str] = None,
    attribute_value: Optional[str] = None,
    realm: Optional[str] = None,
    activate: Optional[bool] = None,
    admin: Optional[bool] = None,
    deny: Optional[bool] = None,
    assign_to_group: Optional[str] = None,
    owner_domains: Optional[str] = None,
    enabled: Optional[bool] = None,
) -> Optional[dict]:
    """Update an existing attribute rule."""

    with get_session() as session:
        rule = (
            session.query(AttributeRule)
            .filter(AttributeRule.id == rule_id)
            .with_for_update()
            .first()
        )
        if not rule:
            return None

        if name is not None:
            rule.name = name
        if attribute_name is not None:
            rule.attribute_name = attribute_name
        if attribute_condition is not None:
            rule.attribute_condition = AttributeConditionEnum(attribute_condition)
        if attribute_value is not None:
            rule.attribute_value = attribute_value
        if realm is not None:
            rule.realm = realm
        if activate is not None:
            rule.activate = activate
        if admin is not None:
            rule.admin = admin
        if deny is not None:
            rule.deny = deny
        if assign_to_group is not None:
            rule.assign_to_group = assign_to_group
        if owner_domains is not None:
            rule.owner_domains = owner_domains
        if enabled is not None:
            rule.enabled = enabled

        log.info(f"Attribute rule {rule_id} updated.")
        return rule.as_dict()


def rule_delete(rule_id: int) -> bool:
    """Delete an attribute rule by ID."""

    with get_session() as session:
        rule = session.query(AttributeRule).filter(AttributeRule.id == rule_id).first()
        if not rule:
            return False
        session.delete(rule)
        log.info(f"Attribute rule {rule_id} deleted.")
        return True


def _match_condition(
    condition: AttributeConditionEnum, claim_value: str, rule_value: str
) -> bool:
    """Evaluate a single condition against a claim value."""

    match condition:
        case AttributeConditionEnum.EQUALS:
            return claim_value == rule_value
        case AttributeConditionEnum.NOT_EQUALS:
            return claim_value != rule_value
        case AttributeConditionEnum.CONTAINS:
            return rule_value in claim_value
        case AttributeConditionEnum.NOT_CONTAINS:
            return rule_value not in claim_value
        case AttributeConditionEnum.STARTS_WITH:
            return claim_value.startswith(rule_value)
        case AttributeConditionEnum.ENDS_WITH:
            return claim_value.endswith(rule_value)
        case AttributeConditionEnum.REGEX_MATCH:
            try:
                return bool(re.search(rule_value, claim_value))
            except re.error:
                log.warning(f"Invalid regex in attribute rule: {rule_value}")
                return False
        case _:
            return False


def _get_claim_values(decoded_jwt: dict, attribute_name: str) -> list[str]:
    """
    Extract claim values from a decoded JWT.
    Handles both single-value and multi-value (list) claims.
    """

    value = decoded_jwt.get(attribute_name)

    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    return [str(value)]


def evaluate_rules(decoded_jwt: dict, user: dict) -> dict:
    """
    Evaluate all enabled attribute rules against a decoded JWT token.
    Returns a dict of actions to apply to the user.

    Parameters:
        decoded_jwt: The decoded JWT payload with all claims.
        user: The user dict from user_create.

    Returns:
        dict with keys: activate, admin, deny, groups
    """

    realm = user.get("realm", "")
    username = user.get("username", "")
    user_id = user.get("user_id", "")

    # If the user was manually deactivated, skip all auto-provisioning
    if user.get("manually_deactivated", False):
        log.info(
            f"Skipping rule evaluation for user_id={user_id}: manually deactivated."
        )
        return {}

    actions = {
        "activate": False,
        "admin": False,
        "deny": False,
        "groups": [],
    }

    with get_session() as session:
        rules = (
            session.query(AttributeRule)
            .filter(AttributeRule.enabled == True)  # noqa: E712
            .order_by(AttributeRule.id)
            .all()
        )

        for rule in rules:
            # Check realm scope
            if rule.realm:
                rule_realms = [r.strip() for r in rule.realm.split(",") if r.strip()]
                if rule_realms and realm not in rule_realms:
                    continue

            claim_values = _get_claim_values(decoded_jwt, rule.attribute_name)

            if not claim_values:
                continue

            matched = any(
                _match_condition(rule.attribute_condition, cv, rule.attribute_value)
                for cv in claim_values
            )

            if not matched:
                continue

            rule_actions = []
            if rule.deny:
                actions["deny"] = True
                rule_actions.append("deny")

            if rule.activate:
                actions["activate"] = True
                rule_actions.append("activate")

            if rule.admin:
                actions["admin"] = True
                rule_actions.append("grant admin")

            if rule.assign_to_group:
                actions["groups"].append(rule.assign_to_group)
                rule_actions.append(f"assign to group {rule.assign_to_group}")

            log.info(
                f"Rule '{rule.name}' matched for user_id={user_id}: "
                f"{rule.attribute_name} {rule.attribute_condition.value} "
                f"'{rule.attribute_value}' -> {', '.join(rule_actions)}."
            )

    return actions


def apply_rule_actions(actions: dict, user: dict) -> None:
    """
    Apply the evaluated rule actions to a user.

    Parameters:
        actions: The actions dict from evaluate_rules.
        user: The user dict (must contain user_id, username).
    """

    if not actions:
        return

    user_id = user.get("user_id", "")
    username = user.get("username", "")

    with get_session() as session:
        db_user = session.query(User).filter(User.user_id == user_id).first()
        if not db_user:
            return

        if actions.get("deny"):
            log.info(f"Deny rule matched for user_id={user_id}, deactivating.")
            db_user.active = False
            return

        if actions.get("activate") and not db_user.active:
            log.info(f"Auto-activating user_id={user_id} via attribute rule.")
            db_user.active = True

        if actions.get("admin") and not db_user.admin:
            log.info(f"Auto-granting admin to user_id={user_id} via attribute rule.")
            db_user.admin = True

    # Group assignments (outside the user session to avoid nested session issues)
    for group_id in actions.get("groups", []):
        try:
            group_add_user(int(group_id), username)
        except (ValueError, TypeError):
            log.warning(
                f"Could not assign user_id={user_id} to group {group_id}."
            )


def _user_to_pseudo_jwt(user: User) -> dict:
    """Build a pseudo-JWT dict from stored user fields for rule testing."""
    username = user.username or ""
    domain = username.split("@")[-1] if "@" in username else ""
    return {
        "preferred_username": username,
        "email": user.email or "",
        "realm": user.realm or "",
        "domain": domain,
    }


def test_rules(rule_ids: list[int], realm: str | list[str] | None = None) -> list[dict]:
    """
    Test which users would be matched by the given rules.

    Returns a list of dicts with user info and which rules matched.
    """
    with get_session() as session:
        rules = (
            session.query(AttributeRule)
            .filter(AttributeRule.id.in_(rule_ids))
            .all()
        )
        if not rules:
            return []

        # Build group ID → name map for display
        group_ids = set()
        for r in rules:
            if r.assign_to_group:
                try:
                    group_ids.add(int(r.assign_to_group))
                except (ValueError, TypeError):
                    pass
        group_names = {}
        if group_ids:
            groups = session.query(Group).filter(Group.id.in_(group_ids)).all()
            group_names = {str(g.id): g.name for g in groups}

        query = session.query(User).filter(
            User.deleted == False,  # noqa: E712
            User.username != "api_user",
        )
        if realm and realm != "*":
            if isinstance(realm, list):
                query = query.filter(User.realm.in_(realm))
            else:
                query = query.filter(User.realm == realm)

        users = query.all()
        results = []

        for user in users:
            pseudo_jwt = _user_to_pseudo_jwt(user)
            matched_rules = []

            for rule in rules:
                if rule.realm:
                    rule_realms = [r.strip() for r in rule.realm.split(",") if r.strip()]
                    if rule_realms and user.realm not in rule_realms:
                        continue

                claim_values = _get_claim_values(pseudo_jwt, rule.attribute_name)
                if not claim_values:
                    continue

                matched = any(
                    _match_condition(rule.attribute_condition, cv, rule.attribute_value)
                    for cv in claim_values
                )
                if matched:
                    rule_info = {"id": rule.id, "name": rule.name}
                    actions = []
                    if rule.activate:
                        actions.append("Activate")
                    if rule.deny:
                        actions.append("Deny")
                    if rule.admin:
                        actions.append("Grant admin")
                    if rule.assign_to_group:
                        gname = group_names.get(rule.assign_to_group, rule.assign_to_group)
                        actions.append(f"Group: {gname}")
                    rule_info["actions"] = actions
                    matched_rules.append(rule_info)

            if matched_rules:
                results.append({
                    "username": user.username,
                    "email": user.email or "",
                    "realm": user.realm,
                    "active": user.active,
                    "admin": user.admin,
                    "matched_rules": matched_rules,
                })

        return results
