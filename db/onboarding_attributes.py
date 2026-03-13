from db.models import OnboardingAttribute
from db.session import get_session
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


def seed_default_attributes() -> None:
    """Insert default attributes if the table is empty."""
    with get_session() as session:
        if session.query(OnboardingAttribute).first():
            return
        for attr in DEFAULT_ATTRIBUTES:
            session.add(OnboardingAttribute(**attr))


def attribute_get_all() -> list[dict]:
    """Return all supported onboarding attributes."""
    with get_session() as session:
        attrs = session.query(OnboardingAttribute).order_by(OnboardingAttribute.name).all()
        return [a.as_dict() for a in attrs]


def attribute_add(
    name: str,
    description: str = "",
    example: str = "",
) -> Optional[dict]:
    """Add a new supported onboarding attribute."""
    with get_session() as session:
        if session.query(OnboardingAttribute).filter(
            OnboardingAttribute.name == name
        ).first():
            return None
        attr = OnboardingAttribute(name=name, description=description, example=example)
        session.add(attr)
        return attr.as_dict()


def attribute_delete(attribute_id: int) -> bool:
    """Delete a supported onboarding attribute by ID."""
    with get_session() as session:
        attr = session.query(OnboardingAttribute).filter(
            OnboardingAttribute.id == attribute_id
        ).first()
        if not attr:
            return False
        session.delete(attr)
        return True
