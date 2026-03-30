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
from fastapi.responses import JSONResponse, Response
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

from utils.log import get_logger

from auth.oidc import get_current_admin_user

from utils.validators import (
    CreateCustomerRequest,
    UpdateCustomerRequest,
)

log = get_logger()
router = APIRouter(tags=["admin"])


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

    customers = await customer_get_all(admin_user)

    result = []

    for customer in customers:
        stats = await customer_get_statistics(customer["id"])
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
        log.warning(f"Non-BOFH user {admin_user['user_id']} denied access to create customer")
        return JSONResponse(content={"error": "User not authorized"}, status_code=403)

    if not item.partner_id or not item.name:
        return JSONResponse(
            content={"error": "Missing required fields"}, status_code=400
        )

    customer = await customer_create(
        customer_abbr=item.customer_abbr,
        partner_id=item.partner_id,
        name=item.name,
        priceplan=item.priceplan,
        base_fee=item.base_fee,
        realms=item.realms,
        contact_email=item.contact_email,
        support_contact_email=item.support_contact_email,
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

    if not (customer := await customer_get(customer_id)):
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
        log.warning(f"Non-BOFH user {admin_user['user_id']} denied access to update customer {customer_id}")
        return JSONResponse(content={"error": "User not authorized"}, status_code=403)

    customer = await customer_update(
        customer_id,
        customer_abbr=item.customer_abbr,
        partner_id=item.partner_id,
        name=item.name,
        priceplan=item.priceplan,
        base_fee=item.base_fee,
        realms=item.realms,
        contact_email=item.contact_email,
        support_contact_email=item.support_contact_email,
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
        log.warning(f"Non-BOFH user {admin_user['user_id']} denied access to delete customer {customer_id}")
        return JSONResponse(content={"error": "User not authorized"}, status_code=403)

    if not await customer_delete(customer_id):
        return JSONResponse(content={"error": "Customer not found"}, status_code=404)

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
        log.warning(f"Non-BOFH user {admin_user['user_id']} denied access to list realms")
        return JSONResponse(content={"error": "User not authorized"}, status_code=403)

    return JSONResponse(content={"result": await get_all_realms()})


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
        log.warning(f"User {admin_user['user_id']} denied access to customer stats {customer_id}")
        return JSONResponse(content={"error": "User not authorized"}, status_code=403)

    if not await customer_get(customer_id):
        return JSONResponse(content={"error": "Customer not found"}, status_code=404)

    return JSONResponse(content={"result": await customer_get_statistics(customer_id)})


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
        log.warning(f"User {admin_user['user_id']} denied access to export customers CSV")
        return JSONResponse(content={"error": "User not authorized"}, status_code=403)

    if not (csv_data := (await export_customers_to_csv(admin_user)).encode("utf-8")):
        return JSONResponse(
            content={"error": "No customer data to export"}, status_code=404
        )

    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="customers_export.csv"'},
    )
