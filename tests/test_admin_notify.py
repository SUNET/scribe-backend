"""Admin lookup for new-user notifications with multi-realm admin_domains."""

import os

import pytest
import pytest_asyncio

os.environ["API_DATABASE_URL"] = "sqlite://"

from contextlib import asynccontextmanager
from unittest.mock import patch
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from db.models import User
from db.user import users_admin_domains_from_realm


@pytest_asyncio.fixture()
async def session():
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    s = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)()

    @asynccontextmanager
    async def _get():
        yield s
        await s.flush()

    with patch("db.user.get_async_session", _get):
        yield s
    await s.close()
    await engine.dispose()


def _admin(uid, domains):
    return User(
        user_id=uid, username=uid, realm="x.se", admin=True,
        admin_domains=domains, transcribed_seconds=0,
    )


@pytest.mark.asyncio
async def test_multi_realm_admin_domains_match(session):
    session.add_all([
        _admin("single", "a.se"),
        _admin("multi", "b.se, a.se ,c.se"),
        _admin("other", "b.se"),
        _admin("suffix", "kau.a.se"),
    ])
    await session.flush()

    found = {u["user_id"] for u in await users_admin_domains_from_realm("a.se")}
    assert found == {"single", "multi"}


# ---------------------------------------------------------------------------
# Quota alerts (sync sessions): only admins who list the exact realm are mailed
# ---------------------------------------------------------------------------

from contextlib import contextmanager
from unittest.mock import MagicMock

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session

from db.models import Customer, Group, GroupUserLink, Job, JobStatusEnum, JobType, NotificationsSent


@pytest.fixture()
def sync_db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)

    @contextmanager
    def _get():
        with Session(engine) as s:
            yield s

    yield _get
    engine.dispose()


def _quota_admin(uid, domains):
    return User(
        user_id=uid, username=uid, realm="x.se", admin=True, admin_domains=domains,
        transcribed_seconds=0, notifications="quota", email=f"{uid}@x.se",
    )


def test_group_quota_alert_ignores_substring_admins(sync_db):
    from datetime import UTC, datetime
    import db.group as dbg

    with sync_db() as s:
        g = Group(name="G", realm="kth.se", quota_seconds=100, transcribed_seconds=0)
        s.add(g)
        s.add_all([
            _quota_admin("exact", "kth.se"),
            _quota_admin("multi", "su.se,kth.se"),
            _quota_admin("sub", "student.kth.se"),
        ])
        s.flush()
        s.add(Job(
            user_id="exact", uuid="j1", job_type=JobType.TRANSCRIPTION,
            status=JobStatusEnum.COMPLETED, transcribed_seconds=99,
            created_at=datetime.now(UTC).replace(tzinfo=None),
        ))
        exact = s.query(User).filter_by(user_id="exact").one()
        s.add(GroupUserLink(group_id=g.id, user_id=exact.id))
        s.commit()

    mock = MagicMock()
    mock.notification_sent_record_exists.return_value = False
    with patch.object(dbg, "get_session", sync_db), patch.object(dbg, "notifications", mock):
        dbg.check_group_quota_alerts()

    sent = {c.kwargs["to_email"] for c in mock.send_group_quota_alert.call_args_list}
    assert sent == {"exact@x.se", "multi@x.se"}


def test_customer_quota_alert_exact_realm_and_monthly_key(sync_db):
    import db.customer as dbc

    with sync_db() as s:
        s.add(Customer(
            name="C", customer_abbr="C", partner_id="p", realms="kth.se,student.kth.se", priceplan="fixed",
            blocks_purchased=1,
        ))
        s.add_all([
            _quota_admin("exact", "kth.se"),
            _quota_admin("sub", "student.kth.se"),
            _quota_admin("other", "xkth.se"),
        ])
        s.commit()

    mock = MagicMock()
    mock.notification_sent_record_exists.return_value = False
    stats = {"minutes_included": 100, "total_transcribed_minutes": 99}
    with (
        patch.object(dbc, "get_session", sync_db),
        patch.object(dbc, "notifications", mock),
        patch.object(dbc, "_customer_get_statistics_sync", return_value=stats),
    ):
        dbc.check_quota_alerts()

    sent = {c.kwargs["to_email"] for c in mock.send_quota_alert.call_args_list}
    assert sent == {"exact@x.se", "sub@x.se"}

    # Dedup key carries the month, so next month's alert is not suppressed
    key = mock.notification_sent_record_add.call_args.args[1]
    assert ":" in key and len(key.split(":")[1]) == 7
