from sqlalchemy import select

from db.models import OnboardingAttribute
from db.session import get_async_session
from typing import Optional


# Default attributes to seed the table with
DEFAULT_ATTRIBUTES = [
    {
        "name": "email",
        "description": "E-mail address",
        "example": "user@example.com",
    },
    {
        "name": "preferred_username",
        "description": "User's preferred username",
        "example": "jdoe",
    },
    {
        "name": "domain",
        "description": "Domain part of the username",
        "example": "example.com",
    },
    {
        "name": "affiliation",
        "description": "Role within institution",
        "example": "employee@example.com",
    },
    {
        "name": "realm",
        "description": "User's authentication realm",
        "example": "example.com",
    },
]


async def seed_default_attributes() -> None:
    """Insert default attributes if the table is empty."""
    async with get_async_session() as session:
        result = await session.execute(select(OnboardingAttribute))
        if result.scalars().first():
            return
        for attr in DEFAULT_ATTRIBUTES:
            session.add(OnboardingAttribute(**attr))


async def attribute_get_all() -> list[dict]:
    """Return all supported onboarding attributes."""
    async with get_async_session() as session:
        result = await session.execute(
            select(OnboardingAttribute).order_by(OnboardingAttribute.name)
        )
        attrs = result.scalars().all()
        return [a.as_dict() for a in attrs]


async def attribute_add(
    name: str,
    description: str = "",
    example: str = "",
) -> Optional[dict]:
    """Add a new supported onboarding attribute."""
    async with get_async_session() as session:
        result = await session.execute(
            select(OnboardingAttribute).where(OnboardingAttribute.name == name)
        )
        if result.scalars().first():
            return None
        attr = OnboardingAttribute(name=name, description=description, example=example)
        session.add(attr)
        return attr.as_dict()


async def attribute_delete(attribute_id: int) -> bool:
    """Delete a supported onboarding attribute by ID."""
    async with get_async_session() as session:
        result = await session.execute(
            select(OnboardingAttribute).where(
                OnboardingAttribute.id == attribute_id
            )
        )
        attr = result.scalars().first()
        if not attr:
            return False
        session.delete(attr)
        return True
