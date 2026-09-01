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

"""
Tests for the one-time code that carries a login's tokens from the OIDC
callback to the frontend, replacing the id token and refresh token that
used to travel in the redirect's query string.

Uses an in-memory SQLite database, so nothing here needs a real database or
a real identity provider.
"""

import os
import pytest
import pytest_asyncio

# Point to an in-memory SQLite database before importing any project modules
os.environ["API_DATABASE_URL"] = "sqlite://"

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from db.models import AuthHandoff
from db.auth_handoff import (
    _lookup_hash,
    _seal_key,
    handoff_cleanup,
    handoff_create,
    handoff_redeem,
)
from utils.crypto import decrypt_with_key, derive_key, encrypt_with_key


ID_TOKEN = "header.payload.signature"
REFRESH_TOKEN = "a-refresh-token"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture()
async def db_session():
    """Create a fresh in-memory async SQLite database for each test."""
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    session = factory()
    yield session
    await session.close()
    await engine.dispose()


@pytest_asyncio.fixture(autouse=True)
async def _patch_session(db_session):
    """Patch get_async_session in db.auth_handoff to use the test database."""

    @asynccontextmanager
    async def _get_async_session():
        try:
            yield db_session
            await db_session.commit()
        except Exception:
            await db_session.rollback()
            raise

    with patch("db.auth_handoff.get_async_session", _get_async_session):
        yield


# ---------------------------------------------------------------------------
# Round trip
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_code_returns_the_tokens_it_was_issued_for():
    code = await handoff_create(ID_TOKEN, REFRESH_TOKEN)

    assert code

    tokens = await handoff_redeem(code)

    assert tokens == {"token": ID_TOKEN, "refresh_token": REFRESH_TOKEN}


@pytest.mark.asyncio
async def test_login_without_a_refresh_token_round_trips():
    """A provider that issues no refresh token must still be able to log in."""

    code = await handoff_create(ID_TOKEN)
    tokens = await handoff_redeem(code)

    assert tokens == {"token": ID_TOKEN, "refresh_token": None}


@pytest.mark.asyncio
async def test_every_login_gets_a_different_code():
    codes = {await handoff_create(ID_TOKEN, REFRESH_TOKEN) for _ in range(20)}

    assert len(codes) == 20


# ---------------------------------------------------------------------------
# Single use
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_code_works_once():
    """
    The whole scheme rests on this: a code left in a browser's history is
    worthless because the landing page already spent it.
    """

    code = await handoff_create(ID_TOKEN, REFRESH_TOKEN)

    assert await handoff_redeem(code) is not None
    assert await handoff_redeem(code) is None


@pytest.mark.asyncio
async def test_redeeming_removes_the_row(db_session):
    """Tokens leave the database as they are handed over, not on a sweep."""

    code = await handoff_create(ID_TOKEN, REFRESH_TOKEN)
    await handoff_redeem(code)

    result = await db_session.execute(select(AuthHandoff))

    assert result.scalars().all() == []


@pytest.mark.asyncio
async def test_concurrent_redemptions_produce_one_winner():
    """
    Eight worker processes race for the same code; the DELETE decides.
    Running them on one event loop is not a real race, but it does prove
    the second attempt finds nothing rather than reading a row that a
    later delete would have removed.
    """

    import asyncio

    code = await handoff_create(ID_TOKEN, REFRESH_TOKEN)
    results = await asyncio.gather(*(handoff_redeem(code) for _ in range(4)))

    assert sum(1 for result in results if result is not None) == 1


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unknown_code_is_refused():
    await handoff_create(ID_TOKEN, REFRESH_TOKEN)

    assert await handoff_redeem("not-a-code-anyone-issued") is None


@pytest.mark.asyncio
async def test_empty_code_is_refused():
    assert await handoff_redeem("") is None


@pytest.mark.asyncio
async def test_expired_code_is_refused(db_session):
    code = await handoff_create(ID_TOKEN, REFRESH_TOKEN)

    row = await db_session.get(AuthHandoff, _lookup_hash(code))
    row.expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
    db_session.add(row)
    await db_session.commit()

    assert await handoff_redeem(code) is None


@pytest.mark.asyncio
async def test_expired_row_is_not_deleted_by_a_failed_redemption(db_session):
    """
    An expired code is refused by the same statement that would delete it,
    so the row is left for the sweeper -- which is what test_cleanup then
    covers. Guards against widening the WHERE clause to "delete first, check
    afterwards", which would answer with the tokens.
    """

    code = await handoff_create(ID_TOKEN, REFRESH_TOKEN)

    row = await db_session.get(AuthHandoff, _lookup_hash(code))
    row.expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
    db_session.add(row)
    await db_session.commit()

    await handoff_redeem(code)

    assert await handoff_cleanup() == 1


# ---------------------------------------------------------------------------
# What the row does and does not carry
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_the_row_holds_neither_the_code_nor_the_tokens(db_session):
    """
    A dump of this table must not be a set of working credentials. The code
    is not in it, and the tokens are encrypted under a key derived from the
    code, which is not in it either.
    """

    code = await handoff_create(ID_TOKEN, REFRESH_TOKEN)

    result = await db_session.execute(select(AuthHandoff))
    row = result.scalars().one()

    stored = f"{row.code_hash}{row.id_token}{row.refresh_token}"

    assert code not in stored
    assert ID_TOKEN not in stored
    assert REFRESH_TOKEN not in stored


@pytest.mark.asyncio
async def test_the_stored_handle_does_not_open_the_row(db_session):
    """
    The lookup hash and the encryption key are independent derivations of
    the code. Someone holding the row -- and so the hash -- still cannot
    decrypt what is in it.
    """

    code = await handoff_create(ID_TOKEN, REFRESH_TOKEN)

    result = await db_session.execute(select(AuthHandoff))
    row = result.scalars().one()

    assert bytes.fromhex(row.code_hash) != _seal_key(code)

    with pytest.raises(Exception):
        decrypt_with_key(bytes.fromhex(row.code_hash), row.id_token)


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cleanup_removes_only_expired_rows(db_session):
    stale = await handoff_create(ID_TOKEN, REFRESH_TOKEN)
    fresh = await handoff_create(ID_TOKEN, REFRESH_TOKEN)

    row = await db_session.get(AuthHandoff, _lookup_hash(stale))
    row.expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
    db_session.add(row)
    await db_session.commit()

    assert await handoff_cleanup() == 1
    assert await handoff_redeem(fresh) is not None


# ---------------------------------------------------------------------------
# The crypto helpers underneath
# ---------------------------------------------------------------------------

def test_derive_key_is_deterministic_and_label_separated():
    assert derive_key("secret", b"one") == derive_key("secret", b"one")
    assert derive_key("secret", b"one") != derive_key("secret", b"two")
    assert derive_key("secret", b"one") != derive_key("other", b"one")
    assert len(derive_key("secret", b"one")) == 32


def test_encrypt_with_key_round_trips():
    key = derive_key("secret", b"test")

    assert decrypt_with_key(key, encrypt_with_key(key, "hello")) == "hello"


def test_encrypt_with_key_is_not_deterministic():
    """A fresh nonce every time, so two seals of one value do not match."""

    key = derive_key("secret", b"test")

    assert encrypt_with_key(key, "hello") != encrypt_with_key(key, "hello")


def test_decrypt_with_key_rejects_the_wrong_key():
    blob = encrypt_with_key(derive_key("secret", b"test"), "hello")

    with pytest.raises(Exception):
        decrypt_with_key(derive_key("other", b"test"), blob)


def test_decrypt_with_key_rejects_tampering():
    key = derive_key("secret", b"test")
    blob = bytearray(bytes.fromhex(encrypt_with_key(key, "hello")))
    blob[-1] ^= 0xFF

    with pytest.raises(Exception):
        decrypt_with_key(key, bytes(blob).hex())


# ---------------------------------------------------------------------------
# The request model
# ---------------------------------------------------------------------------

def test_exchange_request_rejects_junk():
    from pydantic import ValidationError

    from utils.validators import AuthExchangeRequest

    assert AuthExchangeRequest(code="a" * 32).code == "a" * 32

    for bad in ("", "short", "a" * 129, "has spaces in it and is long enough"):
        with pytest.raises(ValidationError):
            AuthExchangeRequest(code=bad)

    # Nothing rides along beside the code.
    with pytest.raises(ValidationError):
        AuthExchangeRequest(code="a" * 32, user_id="someone-else")


# ---------------------------------------------------------------------------
# The endpoints
# ---------------------------------------------------------------------------

@pytest.fixture
def api_client(monkeypatch):
    """
    The real application, driven without its startup events -- the scheduler
    has nothing to do with logging in.
    """

    from fastapi.testclient import TestClient

    import app as app_module

    return TestClient(app_module.app), app_module


def test_exchange_returns_the_tokens_for_a_good_code(api_client, monkeypatch):
    client, app_module = api_client

    async def redeem(code):
        return {"token": ID_TOKEN, "refresh_token": REFRESH_TOKEN} if code == "c" * 32 else None

    monkeypatch.setattr(app_module, "handoff_redeem", redeem)

    response = client.post("/api/auth/exchange", json={"code": "c" * 32})

    assert response.status_code == 200
    assert response.json() == {"token": ID_TOKEN, "refresh_token": REFRESH_TOKEN}


def test_exchange_refuses_a_bad_code(api_client, monkeypatch):
    client, app_module = api_client

    async def redeem(code):
        return None

    monkeypatch.setattr(app_module, "handoff_redeem", redeem)

    response = client.post("/api/auth/exchange", json={"code": "c" * 32})

    assert response.status_code == 400
    assert "token" not in response.json()


def test_exchange_rejects_a_malformed_body(api_client):
    client, _ = api_client

    assert client.post("/api/auth/exchange", json={}).status_code == 422
    assert client.post("/api/auth/exchange", json={"code": "x"}).status_code == 422
    assert (
        client.post(
            "/api/auth/exchange", json={"code": "c" * 32, "user_id": "someone"}
        ).status_code
        == 422
    )


def test_the_login_redirect_carries_a_code_and_no_tokens(api_client, monkeypatch):
    """
    The regression this whole change exists for: nothing that works as a
    credential may appear in the URL the browser is sent to.
    """

    client, app_module = api_client

    async def authorize(request):
        return {
            "id_token": ID_TOKEN,
            "refresh_token": REFRESH_TOKEN,
            "access_token": "an-access-token",
            "userinfo": {"sub": "user-1"},
        }

    async def create(id_token, refresh_token=None):
        assert id_token == ID_TOKEN
        assert refresh_token == REFRESH_TOKEN
        return "c" * 32

    monkeypatch.setattr(app_module.oauth.auth0, "authorize_access_token", authorize)
    monkeypatch.setattr(app_module, "handoff_create", create)

    response = client.get("/api/auth", follow_redirects=False)

    assert response.status_code == 307

    location = response.headers["location"]

    assert "code=" + "c" * 32 in location
    assert ID_TOKEN not in location
    assert REFRESH_TOKEN not in location
    assert "token=" not in location


def test_a_login_that_cannot_be_stored_is_not_completed(api_client, monkeypatch):
    """No falling back to the query string when the handoff row fails."""

    client, app_module = api_client

    async def authorize(request):
        return {
            "id_token": ID_TOKEN,
            "refresh_token": REFRESH_TOKEN,
            "access_token": "an-access-token",
            "userinfo": {"sub": "user-1"},
        }

    async def create(id_token, refresh_token=None):
        return None

    monkeypatch.setattr(app_module.oauth.auth0, "authorize_access_token", authorize)
    monkeypatch.setattr(app_module, "handoff_create", create)

    location = client.get("/api/auth", follow_redirects=False).headers["location"]

    assert "error=login_failed" in location
    assert ID_TOKEN not in location
    assert REFRESH_TOKEN not in location
