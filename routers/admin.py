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

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from db.user import (
    user_delete,
    user_get,
    users_statistics,
    user_get_all,
    user_update,
    group_statistics,
)
from db.group import (
    group_get,
    group_get_all,
    group_create,
    group_update,
    group_delete,
    group_add_user,
    group_remove_user,
)
from db.customer import (
    customer_create,
    customer_get,
    customer_get_all,
    customer_update,
    customer_delete,
    customer_get_statistics,
    get_all_realms,
    export_customers_to_csv,
)
from db.attribute_rules import (
    rule_create,
    rule_get,
    rule_get_all,
    rule_update,
    rule_delete,
    test_rules,
)
from db.onboarding_attributes import (
    attribute_get_all,
    attribute_add,
    attribute_delete,
)

from db.analytics import (
    log_page_view,
    get_page_views,
    get_page_views_summary,
    get_views_per_day,
    get_recent_views,
    get_hourly_heatmap,
    get_hourly_distribution,
    get_week_over_week,
    get_total_stats,
)
from utils.log import get_logger

from utils.settings import get_settings
from auth.oidc import (
    get_current_user,
    get_current_admin_user,
)

from utils.validators import (
    ModifyUserRequest,
    CreateGroupRequest,
    UpdateGroupRequest,
    CreateCustomerRequest,
    UpdateCustomerRequest,
    CreateAttributeRuleRequest,
    UpdateAttributeRuleRequest,
    CreateOnboardingAttributeRequest,
    TestRulesRequest,
)

log = get_logger()
router = APIRouter(tags=["admin"])
settings = get_settings()


@router.get("/admin")
async def statistics(
    request: Request,
    admin_user: dict = Depends(get_current_admin_user),
) -> JSONResponse:
    """
    Get user statistics.
    Used by the frontend to get user statistics.

    Parameters:
        request (Request): The incoming HTTP request.
        admin_user (dict): The current user.

    Returns:
        JSONResponse: The user statistics.
    """

    if admin_user["bofh"]:
        realm = "*"
    else:
        realm = admin_user["realm"]

    return JSONResponse(content={"result": users_statistics(realm=realm)})


@router.get("/admin/users")
async def list_users(
    request: Request,
    admin_user: dict = Depends(get_current_admin_user),
) -> JSONResponse:
    """
    List all users with statistics.
    Used by the frontend to list all users.

    Parameters:
        request (Request): The incoming HTTP request.
        admin_user (dict): The current user.

    Returns:
        JSONResponse: The list of users with statistics.
    """

    if admin_user["bofh"]:
        realm = "*"
    else:
        realm = admin_user["realm"]

    return JSONResponse(content={"result": user_get_all(realm=realm)})


@router.put("/admin/{username}")
async def modify_user(
    request: Request,
    item: ModifyUserRequest,
    username: str,
    admin_user: dict = Depends(get_current_admin_user),
) -> JSONResponse:
    """
    Modify a user's active status.
    Used by the frontend to modify a user's active status.

    Parameters:
        request (Request): The incoming HTTP request.
        username (str): The username of the user to modify.
        admin_user (dict): The current user.

    Returns:
        JSONResponse: The result of the operation.
    """
    if not (user_id := user_get(username=username)["user_id"]):
        return JSONResponse(
            content={"error": "User not found"},
            status_code=404,
        )

    if item.active is not None:
        user_update(
            user_id,
            active=item.active,
        )

    if item.admin is not None:
        user_update(
            user_id,
            admin=item.admin,
        )

    if item.admin_domains is not None:
        user_update(
            user_id,
            admin_domains=item.admin_domains,
        )

    return JSONResponse(content={"result": {"status": "OK"}})


@router.delete("/admin/{username}")
async def delete_user(
    request: Request,
    username: str,
    admin_user: dict = Depends(get_current_admin_user),
) -> JSONResponse:
    """
    Soft-delete a user. The user is marked as deleted and will be
    permanently removed once all associated job data has been cleaned up.

    Parameters:
        request (Request): The incoming HTTP request.
        username (str): The username of the user to delete.
        admin_user (dict): The current user.

    Returns:
        JSONResponse: The result of the operation.
    """

    if not user_delete(username):
        return JSONResponse(
            content={"error": "User not found"},
            status_code=404,
        )

    return JSONResponse(content={"result": {"status": "OK"}})


@router.get("/admin/groups")
async def list_groups(
    request: Request,
    admin_user: dict = Depends(get_current_admin_user),
) -> JSONResponse:
    """
    List all groups with statistics and member counts.

    Parameters:
        request (Request): The incoming HTTP request.
        admin_user (dict): The current user.

    Returns:
        JSONResponse: The list of groups with statistics and member counts.
    """

    if admin_user["bofh"]:
        realm = "*"
    else:
        realm = admin_user["realm"]

    groups = group_get_all(admin_user["user_id"], realm=realm)
    result = []

    for g in groups:
        stats = group_statistics(str(g["id"]), admin_user["user_id"], realm)

        if g["name"] == "All users":
            g["nr_users"] = stats["total_users"]

        group_dict = {
            "id": g["id"],
            "name": g["name"],
            "customer_name": g.get("customer_name", "None"),
            "realm": g["realm"],
            "description": g["description"],
            "created_at": g["created_at"],
            "users": g["users"],
            "nr_users": stats["total_users"],
            "stats": stats,
            "quota_seconds": g["quota_seconds"],
        }

        result.append(group_dict)

    return JSONResponse(content={"result": result})


@router.post("/admin/groups")
async def create_group(
    request: Request,
    item: CreateGroupRequest,
    admin_user: dict = Depends(get_current_admin_user),
) -> JSONResponse:
    """
    Create a new group.

    Parameters:
        request (Request): The incoming HTTP request.
        admin_user (dict): The current user.

    Returns:
        JSONResponse: The result of the operation.
    """

    if not item.name:
        return JSONResponse(content={"error": "Missing group name"}, status_code=400)

    group = group_create(
        name=item.name,
        realm=admin_user["realm"],
        description=item.description,
        quota_seconds=item.quota_seconds,
        owner_user_id=admin_user["user_id"],
    )

    if not group:
        return JSONResponse(
            content={"error": "Failed to create group"}, status_code=500
        )

    return JSONResponse(content={"result": {"id": group["id"], "name": group["name"]}})


@router.get("/admin/groups/{group_id}")
async def get_group(
    request: Request,
    group_id: str,
    admin_user: dict = Depends(get_current_user),
) -> JSONResponse:
    """
    Get group details.

    Parameters:
        request (Request): The incoming HTTP request.
        group_id (str): The ID of the group.
        admin_user (dict): The current user.

    Returns:
        JSONResponse: The group details.
    """

    if admin_user["bofh"]:
        realm = "*"
    else:
        realm = admin_user["realm"]

    group = group_get(group_id, realm=realm, user_id=admin_user["user_id"])

    if not group:
        return JSONResponse(content={"error": "Group not found"}, status_code=404)

    return JSONResponse(content={"result": group})


@router.put("/admin/groups/{group_id}")
async def update_group(
    request: Request,
    item: UpdateGroupRequest,
    group_id: str,
    admin_user: dict = Depends(get_current_admin_user),
) -> JSONResponse:
    """
    Update group details (name/description).

    Parameters:
        request (Request): The incoming HTTP request.
        group_id (str): The ID of the group.
        admin_user (dict): The current user.

    Returns:
        JSONResponse: The result of the operation.
    """

    try:
        if not group_update(
            group_id,
            name=item.name,
            description=item.description,
            usernames=item.usernames,
            quota_seconds=int(item.quota),
        ):
            return JSONResponse(content={"error": "Group not found"}, status_code=404)
    except ValueError as e:
        return JSONResponse(content={"error": str(e)}, status_code=400)

    return JSONResponse(content={"result": {"status": "ok"}})


@router.delete("/admin/groups/{group_id}")
async def delete_group(
    request: Request,
    group_id: int,
    admin_user: dict = Depends(get_current_admin_user),
) -> JSONResponse:
    """
    Delete a group.

    Parameters:
        request (Request): The incoming HTTP request.
        group_id (int): The ID of the group.
        admin_user (dict): The current user.

    Returns:
        JSONResponse: The result of the operation.
    """

    if not group_delete(group_id):
        return JSONResponse(content={"error": "Group not found"}, status_code=404)

    return JSONResponse(content={"result": {"status": "OK"}})


@router.post("/admin/groups/{group_id}/users/{username}")
async def add_user_to_group(
    request: Request,
    group_id: int,
    username: str,
    admin_user: dict = Depends(get_current_admin_user),
) -> JSONResponse:
    """
    Add a user to a group.

    Parameters:
        request (Request): The incoming HTTP request.
        group_id (int): The ID of the group.
        username (str): The username of the user to add.
        admin_user (dict): The current user.

    Returns:
        JSONResponse: The result of the operation.
    """

    if not group_add_user(group_id, username):
        return JSONResponse(
            content={"error": "User or group not found"}, status_code=404
        )

    return JSONResponse(content={"result": {"status": "OK"}})


@router.delete("/admin/groups/{group_id}/users/{username}")
async def remove_user_from_group(
    request: Request,
    group_id: int,
    username: str,
    admin_user: dict = Depends(get_current_admin_user),
) -> JSONResponse:
    """
    Remove a user from a group.

    Parameters:
        admin_user (dict): The current user.
        request (Request): The incoming HTTP request.
        group_id (int): The ID of the group.
        username (str): The username of the user to remove.

    Returns:
        JSONResponse: The result of the operation.
    """

    if not group_remove_user(group_id, username):
        return JSONResponse(
            content={"error": "User or group not found"}, status_code=404
        )

    return JSONResponse(content={"result": {"status": "OK"}})


@router.get("/admin/groups/{group_id}/stats")
async def group_stats(
    request: Request,
    group_id: str,
    admin_user: dict = Depends(get_current_admin_user),
) -> JSONResponse:
    """
    Get group statistics.

    Parameters:
        request (Request): The incoming HTTP request.
        group_id (str): The ID of the group.
        admin_user (dict): The current user.

    Returns:
        JSONResponse: The group statistics.
    """

    if admin_user["bofh"]:
        realm = "*"
    else:
        realm = admin_user["realm"]

    group = group_get(group_id, realm=realm, user_id=admin_user["user_id"])

    if not group:
        return JSONResponse(content={"error": "Group not found"}, status_code=404)

    return JSONResponse(
        content={
            "result": users_statistics(
                group_id, realm=realm, user_id=admin_user["user_id"]
            )
        }
    )


@router.get("/admin/customers", include_in_schema=False)
async def list_customers(
    request: Request,
    admin_user: dict = Depends(get_current_admin_user),
) -> JSONResponse:
    """
    List all customers with statistics.

    Parameters:
        request (Request): The incoming HTTP request.
        admin_user (dict): The current user.

    Returns:
        JSONResponse: The list of customers with statistics.
    """

    customers = customer_get_all(admin_user)

    result = []

    for customer in customers:
        stats = customer_get_statistics(customer["id"])
        customer["stats"] = stats
        result.append(customer)

    return JSONResponse(content={"result": result})


@router.post("/admin/customers", include_in_schema=False)
async def create_customer(
    request: Request,
    item: CreateCustomerRequest,
    admin_user: dict = Depends(get_current_admin_user),
) -> JSONResponse:
    """
    Create a new customer.

    Parameters:
        request (Request): The incoming HTTP request.
        admin_user (dict): The current user.

    Returns:
        JSONResponse: The result of the operation.
    """

    if not admin_user["bofh"]:
        return JSONResponse(content={"error": "User not authorized"}, status_code=403)

    if not item.partner_id or not item.name:
        return JSONResponse(
            content={"error": "Missing required fields"}, status_code=400
        )

    customer = customer_create(
        customer_abbr=item.customer_abbr,
        partner_id=item.partner_id,
        name=item.name,
        priceplan=item.priceplan,
        base_fee=item.base_fee,
        realms=item.realms,
        contact_email=item.contact_email,
        notes=item.notes,
        blocks_purchased=item.blocks_purchased,
    )

    return JSONResponse(content={"result": customer})


@router.get("/admin/customers/{customer_id}", include_in_schema=False)
async def get_customer(
    request: Request,
    customer_id: str,
    admin_user: dict = Depends(get_current_admin_user),
) -> JSONResponse:
    """
    Get customer details.

    Parameters:
        request (Request): The incoming HTTP request.
        customer_id (str): The ID of the customer.
        admin_user (dict): The current user.

    Returns:
        JSONResponse: The customer details.
    """

    if not (customer := customer_get(customer_id)):
        return JSONResponse(content={"error": "Customer not found"}, status_code=404)

    return JSONResponse(content={"result": customer})


@router.put("/admin/customers/{customer_id}", include_in_schema=False)
async def update_customer(
    request: Request,
    item: UpdateCustomerRequest,
    customer_id: str,
    admin_user: dict = Depends(get_current_admin_user),
) -> JSONResponse:
    """
    Update customer details.

    Parameters:
        request (Request): The incoming HTTP request.
        customer_id (str): The ID of the customer.
        admin_user (dict): The current user.

    Returns:
        JSONResponse: The updated customer details.
    """

    if not admin_user["bofh"]:
        return JSONResponse(content={"error": "User not authorized"}, status_code=403)

    customer = customer_update(
        customer_id,
        customer_abbr=item.customer_abbr,
        partner_id=item.partner_id,
        name=item.name,
        priceplan=item.priceplan,
        base_fee=item.base_fee,
        realms=item.realms,
        contact_email=item.contact_email,
        notes=item.notes,
        blocks_purchased=item.blocks_purchased,
    )

    if not customer:
        return JSONResponse(content={"error": "Customer not found"}, status_code=404)

    return JSONResponse(content={"result": customer})


@router.delete("/admin/customers/{customer_id}", include_in_schema=False)
async def delete_customer(
    request: Request,
    customer_id: int,
    admin_user: dict = Depends(get_current_admin_user),
) -> JSONResponse:
    """
    Delete a customer.

    Parameters:
        request (Request): The incoming HTTP request.
        customer_id (int): The ID of the customer.
        admin_user (dict): The current user.

    Returns:
        JSONResponse: The result of the operation.
    """

    if not admin_user["bofh"]:
        return JSONResponse(content={"error": "User not authorized"}, status_code=403)

    if not customer_delete(customer_id):
        return JSONResponse(content={"error": "Customer not found"}, status_code=404)

    return JSONResponse(content={"result": {"status": "OK"}})


# ── Attribute Rules ──────────────────────────────────────────────────────


def _get_admin_allowed_realms(admin_user: dict) -> list[str]:
    """Return the list of realms a non-BOFH admin may manage rules for."""
    realms = set()
    if admin_user.get("realm"):
        realms.add(admin_user["realm"])
    for d in (admin_user.get("admin_domains") or "").split(","):
        d = d.strip()
        if d:
            realms.add(d)
    return sorted(realms)


def _rule_realm_overlaps(rule_realm: str | None, allowed: list[str]) -> bool:
    """Check if any of the rule's comma-separated realms overlap with allowed."""
    if not rule_realm:
        return True
    rule_realms = {r.strip() for r in rule_realm.split(",") if r.strip()}
    return bool(rule_realms & set(allowed))


@router.get("/admin/rules")
async def list_rules(
    request: Request,
    admin_user: dict = Depends(get_current_admin_user),
) -> JSONResponse:
    """List all attribute rules."""

    if admin_user["bofh"]:
        realm = "*"
    else:
        realm = _get_admin_allowed_realms(admin_user)

    return JSONResponse(content={"result": rule_get_all(realm=realm)})


@router.post("/admin/rules")
async def create_rule(
    request: Request,
    item: CreateAttributeRuleRequest,
    admin_user: dict = Depends(get_current_admin_user),
) -> JSONResponse:
    """Create a new attribute rule."""

    if not item.name or not item.attribute_name or not item.attribute_value:
        return JSONResponse(
            content={"error": "Missing required fields"}, status_code=400
        )

    if admin_user["bofh"]:
        realm = item.realm
    else:
        allowed = _get_admin_allowed_realms(admin_user)
        realm = item.realm if item.realm in allowed else allowed[0]

    rule = rule_create(
        name=item.name,
        attribute_name=item.attribute_name,
        attribute_condition=item.attribute_condition,
        attribute_value=item.attribute_value,
        realm=realm,
        activate=item.activate,
        admin=item.admin,
        deny=item.deny,
        assign_to_group=item.assign_to_group,
        assign_to_admin_domains=item.assign_to_admin_domains,
        owner_domains=item.owner_domains,
        enabled=item.enabled,
    )

    return JSONResponse(content={"result": rule})


@router.get("/admin/rules/{rule_id}")
async def get_rule(
    request: Request,
    rule_id: int,
    admin_user: dict = Depends(get_current_admin_user),
) -> JSONResponse:
    """Get a single attribute rule."""

    rule = rule_get(rule_id)
    if not rule:
        return JSONResponse(content={"error": "Rule not found"}, status_code=404)

    if not admin_user["bofh"]:
        allowed = _get_admin_allowed_realms(admin_user)
        if not _rule_realm_overlaps(rule.get("realm"), allowed):
            return JSONResponse(
                content={"error": "Not authorized"}, status_code=403
            )

    return JSONResponse(content={"result": rule})


@router.put("/admin/rules/{rule_id}")
async def update_rule_endpoint(
    request: Request,
    rule_id: int,
    item: UpdateAttributeRuleRequest,
    admin_user: dict = Depends(get_current_admin_user),
) -> JSONResponse:
    """Update an attribute rule."""

    if not admin_user["bofh"]:
        existing = rule_get(rule_id)
        if not existing:
            return JSONResponse(
                content={"error": "Rule not found"}, status_code=404
            )
        allowed = _get_admin_allowed_realms(admin_user)
        if not _rule_realm_overlaps(existing.get("realm"), allowed):
            return JSONResponse(
                content={"error": "Not authorized"}, status_code=403
            )
        # Prevent non-BOFH from moving rule to a realm they don't manage
        if item.realm is not None:
            new_realms = {r.strip() for r in item.realm.split(",") if r.strip()}
            if not new_realms.issubset(set(allowed)):
                item.realm = existing["realm"]

    rule = rule_update(
        rule_id,
        name=item.name,
        attribute_name=item.attribute_name,
        attribute_condition=item.attribute_condition,
        attribute_value=item.attribute_value,
        realm=item.realm,
        activate=item.activate,
        admin=item.admin,
        deny=item.deny,
        assign_to_group=item.assign_to_group,
        assign_to_admin_domains=item.assign_to_admin_domains,
        owner_domains=item.owner_domains,
        enabled=item.enabled,
    )

    if not rule:
        return JSONResponse(content={"error": "Rule not found"}, status_code=404)

    return JSONResponse(content={"result": rule})


@router.delete("/admin/rules/{rule_id}")
async def delete_rule_endpoint(
    request: Request,
    rule_id: int,
    admin_user: dict = Depends(get_current_admin_user),
) -> JSONResponse:
    """Delete an attribute rule."""

    if not admin_user["bofh"]:
        existing = rule_get(rule_id)
        if not existing:
            return JSONResponse(
                content={"error": "Rule not found"}, status_code=404
            )
        allowed = _get_admin_allowed_realms(admin_user)
        if not _rule_realm_overlaps(existing.get("realm"), allowed):
            return JSONResponse(
                content={"error": "Not authorized"}, status_code=403
            )

    if not rule_delete(rule_id):
        return JSONResponse(content={"error": "Rule not found"}, status_code=404)

    return JSONResponse(content={"result": {"status": "OK"}})


@router.post("/admin/rules/test")
async def test_rules_endpoint(
    request: Request,
    item: TestRulesRequest,
    admin_user: dict = Depends(get_current_admin_user),
) -> JSONResponse:
    """Test which users would be matched by the given rules."""

    if not item.rule_ids:
        return JSONResponse(
            content={"error": "No rule IDs provided"}, status_code=400
        )

    if admin_user["bofh"]:
        realm = "*"
    else:
        allowed = _get_admin_allowed_realms(admin_user)
        realm = allowed

    matches = test_rules(item.rule_ids, realm=realm)

    return JSONResponse(content={"result": matches})


# ── Onboarding Attributes ───────────────────────────────────────────────


@router.get("/admin/attributes")
async def list_attributes(
    request: Request,
    admin_user: dict = Depends(get_current_admin_user),
) -> JSONResponse:
    """List all supported onboarding attributes."""

    return JSONResponse(content={"result": attribute_get_all()})


@router.post("/admin/attributes")
async def create_attribute(
    request: Request,
    item: CreateOnboardingAttributeRequest,
    admin_user: dict = Depends(get_current_admin_user),
) -> JSONResponse:
    """Add a new onboarding attribute. BOFH only."""

    if not admin_user["bofh"]:
        return JSONResponse(
            content={"error": "Only BOFH can manage attributes"}, status_code=403
        )

    if not item.name:
        return JSONResponse(
            content={"error": "Attribute name is required"}, status_code=400
        )

    attr = attribute_add(
        name=item.name, description=item.description, example=item.example
    )
    if not attr:
        return JSONResponse(
            content={"error": "Attribute already exists"}, status_code=409
        )

    return JSONResponse(content={"result": attr})


@router.delete("/admin/attributes/{attribute_id}")
async def delete_attribute(
    request: Request,
    attribute_id: int,
    admin_user: dict = Depends(get_current_admin_user),
) -> JSONResponse:
    """Delete an onboarding attribute. BOFH only."""

    if not admin_user["bofh"]:
        return JSONResponse(
            content={"error": "Only BOFH can manage attributes"}, status_code=403
        )

    if not attribute_delete(attribute_id):
        return JSONResponse(
            content={"error": "Attribute not found"}, status_code=404
        )

    return JSONResponse(content={"result": {"status": "OK"}})


@router.get("/admin/realms", include_in_schema=False)
async def list_realms(
    request: Request,
    admin_user: dict = Depends(get_current_admin_user),
) -> JSONResponse:
    """
    List all unique realms.

    Parameters:
        request (Request): The incoming HTTP request.
        admin_user (dict): The current user.

    Returns:
        JSONResponse: The list of unique realms.
    """

    if not admin_user["bofh"]:
        return JSONResponse(content={"error": "User not authorized"}, status_code=403)

    return JSONResponse(content={"result": get_all_realms()})


@router.get("/admin/customers/{customer_id}/stats", include_in_schema=False)
async def customer_stats(
    request: Request,
    customer_id: str,
    admin_user: dict = Depends(get_current_admin_user),
) -> JSONResponse:
    """
    Get detailed customer statistics.

    Parameters:
        request (Request): The incoming HTTP request.
        customer_id (str): The ID of the customer.
        admin_user (dict): The current user.

    Returns:
        JSONResponse: The customer statistics.
    """

    if not admin_user["bofh"] and not admin_user["admin"]:
        return JSONResponse(content={"error": "User not authorized"}, status_code=403)

    if not customer_get(customer_id):
        return JSONResponse(content={"error": "Customer not found"}, status_code=404)

    return JSONResponse(content={"result": customer_get_statistics(customer_id)})


@router.get("/admin/customers/export/csv")
async def export_customers_csv(
    request: Request,
    admin_user: dict = Depends(get_current_admin_user),
):
    """
    Export all customers with statistics to CSV format.

    Parameters:
        request (Request): The incoming HTTP request.
        admin_user (dict): The current user.

    Returns:
        Response: The CSV file response.
    """

    if not admin_user["bofh"] and not admin_user["admin"]:
        return JSONResponse(content={"error": "User not authorized"}, status_code=403)

    if not (csv_data := export_customers_to_csv(admin_user).encode("utf-8")):
        return JSONResponse(
            content={"error": "No customer data to export"}, status_code=404
        )

    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="customers_export.csv"'},
    )


@router.post("/admin/analytics/log")
async def analytics_log(
    request: Request,
    current_user: dict = Depends(get_current_user),
) -> JSONResponse:
    """
    Log an anonymous page view.
    """
    body = await request.json()
    path = body.get("path", "")
    if path:
        log_page_view(path)
    return JSONResponse(content={"result": "ok"})


@router.get("/admin/analytics/views")
async def analytics_views(
    request: Request,
    admin_user: dict = Depends(get_current_admin_user),
    days: int = 30,
) -> JSONResponse:
    """
    Get page views grouped by path and day. BOFH only.
    """
    if not admin_user.get("bofh"):
        return JSONResponse(content={"error": "User not authorized"}, status_code=403)
    return JSONResponse(content={"result": get_page_views(days=days)})


@router.get("/admin/analytics/summary")
async def analytics_summary(
    request: Request,
    admin_user: dict = Depends(get_current_admin_user),
) -> JSONResponse:
    """
    Get total views per page (all time and last 30 days). BOFH only.
    """
    if not admin_user.get("bofh"):
        return JSONResponse(content={"error": "User not authorized"}, status_code=403)
    return JSONResponse(content={"result": get_page_views_summary()})


@router.get("/admin/analytics/daily")
async def analytics_daily(
    request: Request,
    admin_user: dict = Depends(get_current_admin_user),
    days: int = 30,
) -> JSONResponse:
    """
    Get total views per day. BOFH only.
    """
    if not admin_user.get("bofh"):
        return JSONResponse(content={"error": "User not authorized"}, status_code=403)
    return JSONResponse(content={"result": get_views_per_day(days=days)})


@router.get("/admin/analytics/recent")
async def analytics_recent(
    request: Request,
    admin_user: dict = Depends(get_current_admin_user),
    limit: int = 50,
) -> JSONResponse:
    """
    Get most recent page views. BOFH only.
    """
    if not admin_user.get("bofh"):
        return JSONResponse(content={"error": "User not authorized"}, status_code=403)
    return JSONResponse(content={"result": get_recent_views(limit=limit)})


@router.get("/admin/analytics/heatmap")
async def analytics_heatmap(
    request: Request,
    admin_user: dict = Depends(get_current_admin_user),
    days: int = 30,
) -> JSONResponse:
    """
    Get views grouped by day-of-week and hour-of-day for heatmap. BOFH only.
    """
    if not admin_user.get("bofh"):
        return JSONResponse(content={"error": "User not authorized"}, status_code=403)
    return JSONResponse(content={"result": get_hourly_heatmap(days=days)})


@router.get("/admin/analytics/hourly")
async def analytics_hourly(
    request: Request,
    admin_user: dict = Depends(get_current_admin_user),
    days: int = 30,
) -> JSONResponse:
    """
    Get views per hour-of-day. BOFH only.
    """
    if not admin_user.get("bofh"):
        return JSONResponse(content={"error": "User not authorized"}, status_code=403)
    return JSONResponse(content={"result": get_hourly_distribution(days=days)})


@router.get("/admin/analytics/wow")
async def analytics_week_over_week(
    request: Request,
    admin_user: dict = Depends(get_current_admin_user),
) -> JSONResponse:
    """
    Get week-over-week comparison. BOFH only.
    """
    if not admin_user.get("bofh"):
        return JSONResponse(content={"error": "User not authorized"}, status_code=403)
    return JSONResponse(content={"result": get_week_over_week()})


@router.get("/admin/analytics/stats")
async def analytics_stats(
    request: Request,
    admin_user: dict = Depends(get_current_admin_user),
) -> JSONResponse:
    """
    Get aggregate analytics stats for summary cards. BOFH only.
    """
    if not admin_user.get("bofh"):
        return JSONResponse(content={"error": "User not authorized"}, status_code=403)
    return JSONResponse(content={"result": get_total_stats()})
