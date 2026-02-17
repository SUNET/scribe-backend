import csv
import io

from datetime import datetime, timedelta

from db.job import job_get_all
from db.models import Customer, User
from db.session import get_session
from typing import Optional
from utils.log import get_logger
from utils.notifications import notifications
from utils.settings import get_settings

settings = get_settings()
log = get_logger()


def customer_create(
    customer_abbr: str,
    partner_id: str,
    name: str,
    priceplan: str,
    base_fee: int,
    realms: str,
    contact_email: Optional[str] = None,
    notes: Optional[str] = None,
    blocks_purchased: Optional[int] = 0,
) -> dict:
    """
    Create a new customer in the database.

    Parameters:
        customer_abbr (str): Abbreviation for the customer.
        partner_id (str): Partner ID associated with the customer.
        name (str): Full name of the customer.
        priceplan (str): Pricing plan for the customer (e.g., "fixed", "usage").
        base_fee (int): Base fee for the customer.
        realms (str): Comma-separated list of realms associated with the customer.
        contact_email (Optional[str]): Contact email for the customer.
        notes (Optional[str]): Additional notes about the customer.
        blocks_purchased (Optional[int]): Number of blocks purchased (for fixed plans).

    Returns:
        dict: Dictionary representation of the created customer.
    """

    with get_session() as session:
        customer = Customer(
            customer_abbr=customer_abbr,
            partner_id=partner_id,
            name=name,
            contact_email=contact_email,
            priceplan=priceplan,
            base_fee=base_fee,
            realms=realms,
            notes=notes,
            blocks_purchased=blocks_purchased if blocks_purchased else 0,
        )

        session.add(customer)
        session.flush()

        log.info(f"Customer {customer.name} created with ID {customer.id}.")

        return customer.as_dict()


def customer_get_from_user_id(user_id: str) -> Optional[dict]:
    """
    Get a customer by user_id.

    Parameters:
        user_id (str): The user ID to retrieve the associated customer.

    Returns:
        Optional[dict]: Dictionary representation of the customer if found, else empty dict.
    """

    with get_session() as session:
        if not (user := session.query(User).filter(User.user_id == user_id).first()):
            return {}

        realm = user.realm

        if not (
            customer := (
                session.query(Customer)
                .filter(Customer.realms.like(f"%{realm}%"))
                .first()
            )
        ):
            return {}

        return customer.as_dict()


def customer_get(customer_id: str) -> Optional[dict]:
    """
    Get a customer by id.

    Parameters:
        customer_id (str): The ID of the customer to retrieve.

    Returns:
        Optional[dict]: Dictionary representation of the customer if found, else empty dict.
    """

    with get_session() as session:
        if not (
            customer := session.query(Customer)
            .filter(Customer.id == customer_id)
            .first()
        ):
            return {}

        return customer.as_dict()


def customer_get_by_partner_id(partner_id: str) -> Optional[dict]:
    """
    Get a customer by partner_id.

    Parameters:
        partner_id (str): The partner ID of the customer to retrieve.

    Returns:
        Optional[dict]: Dictionary representation of the customer if found, else empty dict.
    """

    with get_session() as session:
        if not (
            customer := (
                session.query(Customer)
                .filter(Customer.partner_id == partner_id)
                .first()
            )
        ):
            return {}

        return customer.as_dict()


def customer_get_all(admin_user: dict) -> list[dict]:
    """
    Get all customers.

    Parameters:
        admin_user (dict): Dictionary containing admin user details, including 'bofh' and 'realm' keys.

    Returns:
        list[dict]: List of dictionary representations of customers.
    """

    with get_session() as session:
        if admin_user["bofh"]:
            customers = session.query(Customer).all()
            return [customer.as_dict() for customer in customers]
        elif admin_user["admin"]:
            realm = admin_user["realm"]
            customers = session.query(Customer).all()
            matching_customers = []

            for customer in customers:
                customer_realms = [
                    r.strip() for r in customer.realms.split(",") if r.strip()
                ]

                if realm in customer_realms:
                    matching_customers.append(customer.as_dict())

            return matching_customers

        else:
            return []


def customer_update(
    customer_id: Optional[str] = None,
    customer_abbr: Optional[str] = None,
    partner_id: Optional[str] = None,
    name: Optional[str] = None,
    contact_email: Optional[str] = None,
    priceplan: Optional[str] = None,
    base_fee: Optional[int] = None,
    realms: Optional[str] = None,
    notes: Optional[str] = None,
    blocks_purchased: Optional[int] = None,
) -> Optional[dict]:
    """
    Update customer metadata.

    Parameters:
        customer_id (Optional[str]): The ID of the customer to update.
        customer_abbr (Optional[str]): New abbreviation for the customer.
        partner_id (Optional[str]): New partner ID for the customer.
        name (Optional[str]): New name for the customer.
        contact_email (Optional[str]): New contact email for the customer.
        priceplan (Optional[str]): New pricing plan for the customer.
        base_fee (Optional[int]): New base fee for the customer.
        realms (Optional[str]): New comma-separated list of realms for the customer.
        notes (Optional[str]): New notes for the customer.
        blocks_purchased (Optional[int]): New number of blocks purchased.

    Returns:
        Optional[dict]: Dictionary representation of the updated customer if found, else empty dict.
    """

    with get_session() as session:
        if not (
            customer := session.query(Customer)
            .filter(Customer.id == customer_id)
            .with_for_update()
            .first()
        ):
            return {}

        if customer_abbr is not None:
            customer.customer_abbr = customer_abbr
        if partner_id is not None:
            customer.partner_id = partner_id
        if name is not None:
            customer.name = name
        if contact_email is not None:
            customer.contact_email = contact_email
        if priceplan is not None:
            customer.priceplan = priceplan
        if base_fee is not None:
            customer.base_fee = base_fee
        if realms is not None:
            customer.realms = realms
        if notes is not None:
            customer.notes = notes
        if blocks_purchased is not None:
            customer.blocks_purchased = blocks_purchased

        log.info(f"Customer {customer.name} (ID: {customer.id}) updated.")

        return customer.as_dict()


def customer_delete(customer_id: int) -> bool:
    """
    Delete a customer by id.

    Parameters:
        customer_id (int): The ID of the customer to delete.

    Returns:
        bool: True if the customer was deleted, False if not found.
    """
    with get_session() as session:
        if not (
            customer := session.query(Customer)
            .filter(Customer.id == customer_id)
            .first()
        ):
            return False

        session.delete(customer)

    log.info(f"Customer {customer.name} (ID: {customer.id}) deleted.")

    return True


def customer_get_statistics(customer_id: str) -> dict:
    """
    Get statistics for a specific customer.
    Calculates transcription statistics for all users in the customer's realms.
    For fixed plan customers, calculates block usage and overages.

    Parameters:
        customer_id (str): The ID of the customer to get statistics for.

    Returns:
        dict: Dictionary containing customer statistics.
    """

    with get_session() as session:
        if not (
            customer := session.query(Customer)
            .filter(Customer.id == customer_id)
            .first()
        ):
            return {
                "total_users": 0,
                "transcribed_files": 0,
                "transcribed_files_last_month": 0,
                "transcribed_minutes": 0,
                "transcribed_minutes_external": 0,
                "transcribed_minutes_last_month": 0,
                "transcribed_minutes_external_last_month": 0,  # REACH etc
                "total_transcribed_minutes": 0,
                "total_transcribed_minutes_last_month": 0,
                "blocks_purchased": 0,
                "blocks_consumed": 0,
                "minutes_included": 0,
                "overage_minutes": 0,
                "overage_minutes_last_month": 0,
                "remaining_minutes": 0,
            }

        # Get all users associated with this customer's realms
        if not (
            realm_list := [r.strip() for r in customer.realms.split(",") if r.strip()]
        ):
            return {
                "total_users": 0,
                "transcribed_files": 0,
                "transcribed_minutes": 0,
                "transcribed_minutes_external": 0,
                "transcribed_minutes_last_month": 0,
                "transcribed_minutes_external_last_month": 0,  # REACH etc
                "transcribed_files_last_month": 0,
                "total_transcribed_minutes": 0,
                "total_transcribed_minutes_last_month": 0,
                "blocks_purchased": (
                    customer.blocks_purchased if customer.blocks_purchased else 0
                ),
                "blocks_consumed": 0,
                "minutes_included": (
                    customer.blocks_purchased if customer.blocks_purchased else 0
                )
                * settings.CUSTOMER_MINUTES_PER_BLOCK,
                "overage_minutes": 0,
                "overage_minutes_last_month": 0,
                "remaining_minutes": (
                    customer.blocks_purchased if customer.blocks_purchased else 0
                )
                * settings.CUSTOMER_MINUTES_PER_BLOCK,
            }

        users = session.query(User).filter(User.realm.in_(realm_list)).all()

        partner_users = (
            session.query(User).filter(User.username == customer.partner_id).all()
        )

        users.extend(partner_users)

        transcribed_minutes = 0
        transcribed_minutes_external = 0
        transcribed_minutes_last_month = 0
        transcribed_minutes_external_last_month = 0  # REACH etc

        total_transcribed_minutes_current = 0
        total_transcribed_minutes_last = 0
        total_files_current = 0
        total_files_last = 0

        today = datetime.utcnow().date()
        first_day_this_month = today.replace(day=1)
        last_day_prev_month = first_day_this_month - timedelta(days=1)
        first_day_prev_month = last_day_prev_month.replace(day=1)

        for user in users:
            jobs_result = job_get_all(user.user_id, cleaned=True)

            if not jobs_result or "jobs" not in jobs_result:
                continue

            jobs = jobs_result["jobs"]

            for job in jobs:
                try:
                    job_date = datetime.strptime(
                        job["created_at"], "%Y-%m-%d %H:%M:%S.%f"
                    ).date()
                except (ValueError, KeyError):
                    continue

                if job.get("status") == "completed" or job.get("status") == "deleted":
                    transcribed_seconds = job.get("transcribed_seconds", 0)

                    if job_date >= first_day_this_month:
                        total_files_current += 1
                        total_transcribed_minutes_current += transcribed_seconds / 60

                        if user.username.isnumeric():
                            transcribed_minutes_external += transcribed_seconds / 60
                        else:
                            transcribed_minutes += transcribed_seconds / 60

                    elif first_day_prev_month <= job_date <= last_day_prev_month:
                        total_files_last += 1
                        total_transcribed_minutes_last += transcribed_seconds / 60

                        if user.username.isnumeric():
                            transcribed_minutes_external_last_month += (
                                transcribed_seconds / 60
                            )
                        else:
                            transcribed_minutes_last_month += transcribed_seconds / 60

        # Calculate block usage for fixed plan customers
        blocks_purchased = customer.blocks_purchased if customer.blocks_purchased else 0
        minutes_included = blocks_purchased * settings.CUSTOMER_MINUTES_PER_BLOCK

        blocks_consumed = 0
        overage_minutes = 0
        overage_minutes_last_month = 0
        remaining_minutes = 0

        if customer.priceplan == "fixed" and blocks_purchased > 0:
            if total_transcribed_minutes_current > minutes_included:
                blocks_consumed = blocks_purchased
                overage_minutes = total_transcribed_minutes_current - minutes_included
                remaining_minutes = 0
            else:
                # Calculate partial blocks consumed
                blocks_consumed = (
                    total_transcribed_minutes_current
                    / settings.CUSTOMER_MINUTES_PER_BLOCK
                )
                remaining_minutes = minutes_included - total_transcribed_minutes_current

            if transcribed_minutes_last_month > 4000 * blocks_purchased:
                overage_minutes_last_month = total_transcribed_minutes_last - (
                    4000 * blocks_purchased
                )

        return {
            "total_users": len(users),
            "transcribed_files": int(total_files_current),
            "transcribed_files_last_month": int(total_files_last),
            "transcribed_minutes": int(transcribed_minutes),
            "transcribed_minutes_external": int(transcribed_minutes_external),
            "transcribed_minutes_last_month": int(transcribed_minutes_last_month),
            "transcribed_minutes_external_last_month": int(
                transcribed_minutes_external_last_month
            ),
            "total_transcribed_minutes": int(total_transcribed_minutes_current),
            "total_transcribed_minutes_last_month": int(total_transcribed_minutes_last),
            "blocks_purchased": blocks_purchased,
            "blocks_consumed": round(blocks_consumed, 2),
            "minutes_included": minutes_included,
            "overage_minutes": int(overage_minutes),
            "overage_minutes_last_month": int(overage_minutes_last_month),
            "remaining_minutes": int(remaining_minutes),
        }


def get_all_realms() -> list[str]:
    """
    Get all unique realms from users.
    Returns a sorted list of unique realm strings.

    Parameters:
        None

    Returns:
        list[str]: Sorted list of unique realms.
    """
    with get_session() as session:
        realms = session.query(User.realm).distinct().all()
        realm_list = [realm[0] for realm in realms if realm[0]]

        return sorted(realm_list)


def get_customer_name_from_realm(realm: str) -> Optional[str]:
    """
    Get customer name from a realm.
    Returns the customer name if the realm is associated with a customer.

    Parameters:
        realm (str): The realm string to search for.

    Returns:
        Optional[str]: Customer name if found, else None.
    """
    with get_session() as session:
        customers = session.query(Customer).all()

        for customer in customers:
            customer_realms = [
                r.strip() for r in customer.realms.split(",") if r.strip()
            ]
            if realm in customer_realms:
                return customer.name

        return None


def get_customer_by_realm(realm: str) -> Optional[dict]:
    """
    Get customer details by realm.
    Returns the first customer that has this realm in their realms list.

    Parameters:
        realm (str): The realm string to search for.

    Returns:
        Optional[dict]: Customer dictionary if found, else None.
    """
    with get_session() as session:
        customers = session.query(Customer).all()

        for customer in customers:
            customer_realms = [
                r.strip() for r in customer.realms.split(",") if r.strip()
            ]
            if realm in customer_realms:
                return customer.as_dict()

        return None


def customer_list_by_realms(realms: list[str]) -> list[dict]:
    """
    Get all customers that have any of the specified realms.

    Parameters:
        realms: List of realm strings to search for

    Returns:
        List of customer dictionaries
    """
    with get_session() as session:
        customers = session.query(Customer).all()
        matching_customers = []

        for customer in customers:
            customer_realms = [
                r.strip() for r in customer.realms.split(",") if r.strip()
            ]
            if any(realm in customer_realms for realm in realms):
                matching_customers.append(customer.as_dict())

        return matching_customers


def export_customers_to_csv(admin_user: dict) -> str:
    """
    Export all customers with their statistics to CSV format.

    Parameters:
        admin_user (dict): Dictionary containing admin user details.

    Returns:
        CSV string with customer data and statistics
    """

    output = io.StringIO()

    if not (customers := customer_get_all(admin_user)):
        return ""

    # Define CSV headers
    fieldnames = [
        "Customer Name",
        "Customer Abbreviation",
        "Partner ID",
        "Contact Email",
        "Price Plan",
        "Base Fee",
        "Blocks Purchased",
        "Realms",
        "Total Users",
        "Files (This Month)",
        "Files (Last Month)",
        "Total minutes (This Month)",
        "Total minutes (Last Month)",
        "Minutes via Sunet Play (This Month)",
        "Minutes via Sunet Play (Last Month)",
        "Minutes via web interface and API (This Month)",
        "Minutes via web interface and API (Last Month)",
        "Blocks Consumed",
        "Minutes Included",
        "Overage Minutes",
        "Overage Minutes (Last Month)",
        "Remaining Minutes",
        "Notes",
        "Created At",
    ]

    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()

    for customer in customers:
        stats = customer_get_statistics(customer["id"])

        row = {
            "Customer Name": customer.get("name", ""),
            "Customer Abbreviation": customer.get("customer_abbr", ""),
            "Partner ID": customer.get("partner_id", ""),
            "Contact Email": customer.get("contact_email", ""),
            "Price Plan": customer.get("priceplan", "").capitalize(),
            "Base Fee": customer.get("base_fee", 0),
            "Blocks Purchased": customer.get("blocks_purchased", 0),
            "Realms": customer.get("realms", ""),
            "Total Users": stats.get("total_users", 0),
            "Files (This Month)": stats.get("transcribed_files", 0),
            "Files (Last Month)": stats.get("transcribed_files_last_month", 0),
            "Total minutes (This Month)": stats.get("total_transcribed_minutes", 0),
            "Total minutes (Last Month)": stats.get(
                "total_transcribed_minutes_last_month", 0
            ),
            "Minutes via Sunet Play (This Month)": stats.get(
                "transcribed_minutes_external", 0
            ),
            "Minutes via Sunet Play (Last Month)": stats.get(
                "transcribed_minutes_external_last_month", 0
            ),
            "Minutes via web interface and API (This Month)": stats.get(
                "transcribed_minutes", 0
            ),
            "Minutes via web interface and API (Last Month)": stats.get(
                "transcribed_minutes_last_month", 0
            ),
            "Blocks Consumed": stats.get("blocks_consumed", 0),
            "Minutes Included": stats.get("minutes_included", 0),
            "Overage Minutes": stats.get("overage_minutes", 0),
            "Overage Minutes (Last Month)": stats.get("overage_minutes_last_month", 0),
            "Remaining Minutes": stats.get("remaining_minutes", 0),
            "Notes": customer.get("notes", ""),
            "Created At": customer.get("created_at", ""),
        }

        writer.writerow(row)

    return output.getvalue()


def check_quota_alerts() -> None:
    """
    Check all fixed-plan customers for 95%+ block quota consumption.
    Sends email alerts to admin users who have the quota notification enabled.

    Returns:
        None
    """

    with get_session() as session:
        customers = session.query(Customer).filter(
            Customer.priceplan == "fixed",
            Customer.blocks_purchased > 0,
        ).all()

        for customer in customers:
            stats = customer_get_statistics(customer.id)
            minutes_included = stats.get("minutes_included", 0)

            if minutes_included == 0:
                continue

            minutes_consumed = stats.get("total_transcribed_minutes", 0)
            usage_percent = int((minutes_consumed / minutes_included) * 100)

            if usage_percent < 95:
                continue

            realm_list = [r.strip() for r in customer.realms.split(",") if r.strip()]

            for realm in realm_list:
                admin_users = session.query(User).filter(
                    User.admin == True,
                    User.admin_domains.ilike(f"%{realm}%"),
                ).all()

                for admin_user in admin_users:
                    if not admin_user.notifications or "quota" not in admin_user.notifications.split(","):
                        continue

                    if not admin_user.email:
                        continue

                    if notifications.notification_sent_record_exists(
                        admin_user.user_id, str(customer.id), "quota_alert"
                    ):
                        continue

                    notifications.send_quota_alert(
                        to_email=admin_user.email,
                        customer_name=customer.name,
                        usage_percent=usage_percent,
                        blocks_purchased=stats.get("blocks_purchased", 0),
                        minutes_included=minutes_included,
                        minutes_consumed=minutes_consumed,
                        remaining_minutes=stats.get("remaining_minutes", 0),
                    )

                    notifications.notification_sent_record_add(
                        admin_user.user_id, str(customer.id), "quota_alert"
                    )

                    log.info(
                        f"Quota alert sent to {admin_user.email} for customer {customer.name} ({usage_percent}%)"
                    )


def send_weekly_usage_reports() -> None:
    """
    Send weekly usage reports to admin users who have the weekly report notification enabled.

    Returns:
        None
    """

    with get_session() as session:
        customers = session.query(Customer).all()

        for customer in customers:
            stats = customer_get_statistics(customer.id)
            realm_list = [r.strip() for r in customer.realms.split(",") if r.strip()]

            for realm in realm_list:
                admin_users = session.query(User).filter(
                    User.admin == True,
                    User.admin_domains.ilike(f"%{realm}%"),
                ).all()

                for admin_user in admin_users:
                    if not admin_user.notifications or "weekly_report" not in admin_user.notifications.split(","):
                        continue

                    if not admin_user.email:
                        continue

                    notifications.send_weekly_usage_report(
                        to_email=admin_user.email,
                        customer_name=customer.name,
                        total_users=stats.get("total_users", 0),
                        transcribed_files=stats.get("transcribed_files", 0),
                        transcribed_minutes=stats.get("transcribed_minutes", 0),
                        transcribed_minutes_external=stats.get("transcribed_minutes_external", 0),
                        blocks_purchased=stats.get("blocks_purchased", 0),
                        blocks_consumed=stats.get("blocks_consumed", 0),
                        minutes_included=stats.get("minutes_included", 0),
                        remaining_minutes=stats.get("remaining_minutes", 0),
                        overage_minutes=stats.get("overage_minutes", 0),
                    )

                    log.info(
                        f"Weekly usage report sent to {admin_user.email} for customer {customer.name}"
                    )
