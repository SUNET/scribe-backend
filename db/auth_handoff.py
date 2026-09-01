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
The one-time code that carries a login's tokens from the OIDC callback to
the frontend without putting them in a URL.

The callback stores the tokens here and redirects with a code; the
frontend's own server posts that code to /api/auth/exchange and gets the
tokens back over a connection of its own. The browser only ever sees the
code, and by the time the landing page has rendered the code is spent.

Two properties do the work, and both are worth keeping in mind before
changing anything here:

Redemption is one statement -- DELETE ... RETURNING. It is the delete that
decides who won, so a code cannot be redeemed twice however many worker
processes race for it, and the tokens leave the database at the moment they
are handed over rather than lingering until a sweeper notices them.

The code is never stored. What is stored is one HKDF derivation of it as
the lookup handle, while the tokens are encrypted under a second, separate
derivation. Whoever holds the row holds neither. This matters because the
row is, for its minute, a complete set of credentials for a person.
"""

import secrets

from datetime import UTC, datetime, timedelta
from typing import Optional

from sqlalchemy import delete

from db.models import AuthHandoff
from db.session import get_async_session
from utils.crypto import decrypt_with_key, derive_key, encrypt_with_key
from utils.log import get_logger
from utils.settings import get_settings

log = get_logger()
settings = get_settings()

# Bytes of randomness behind a code. At 32 the code is not guessable, which
# is what stands in for a rate limit on an endpoint that has to be reachable
# without a token: there is nothing to throttle when the search space is
# 2**256 and every wrong answer is indistinguishable from every other.
CODE_BYTES = 32

# Labels keeping the two derivations of one code apart. Changing either
# strands codes issued before the change -- harmless, they last a minute,
# but the constants are versioned so that is a deliberate act.
LOOKUP_INFO = b"sunet-scribe-auth-handoff-lookup-v1"
SEAL_INFO = b"sunet-scribe-auth-handoff-seal-v1"


def _lookup_hash(code: str) -> str:
    """
    The stored handle for a code.

    Parameters:
        code (str): The one-time code.

    Returns:
        str: A hex digest to look the row up by.
    """

    return derive_key(code, LOOKUP_INFO).hex()


def _seal_key(code: str) -> bytes:
    """
    The key the tokens in a row are encrypted under.

    Independent of _lookup_hash() by construction: knowing the stored handle
    says nothing about this key, so the row cannot be opened without the
    code itself.

    Parameters:
        code (str): The one-time code.

    Returns:
        bytes: A 32-byte AES-GCM key.
    """

    return derive_key(code, SEAL_INFO)


async def handoff_create(id_token: str, refresh_token: Optional[str] = None) -> Optional[str]:
    """
    Store one login's tokens and return the code that collects them.

    Parameters:
        id_token (str): The OIDC id token.
        refresh_token (Optional[str]): The OIDC refresh token, when the
            provider issued one.

    Returns:
        Optional[str]: The one-time code, or None when the row could not be
            written -- the caller must not fall back to putting the tokens
            in the URL, which is the whole point of this module.
    """

    code = secrets.token_urlsafe(CODE_BYTES)
    key = _seal_key(code)

    expires_at = datetime.now(UTC).replace(tzinfo=None) + timedelta(
        seconds=settings.AUTH_HANDOFF_TTL_SECONDS
    )

    try:
        async with get_async_session() as session:
            session.add(
                AuthHandoff(
                    code_hash=_lookup_hash(code),
                    id_token=encrypt_with_key(key, id_token),
                    refresh_token=(
                        encrypt_with_key(key, refresh_token) if refresh_token else None
                    ),
                    expires_at=expires_at,
                )
            )
    except Exception:
        # Never log the code or the tokens, here or anywhere.
        log.error("Failed to store the login handoff.", exc_info=True)
        return None

    return code


async def handoff_redeem(code: str) -> Optional[dict]:
    """
    Exchange a code for the tokens it was issued for, once.

    Parameters:
        code (str): The one-time code from the redirect.

    Returns:
        Optional[dict]: {"token": ..., "refresh_token": ...} on success, or
            None when the code is unknown, already spent or expired. The
            three are deliberately indistinguishable to the caller.
    """

    if not code:
        return None

    now = datetime.now(UTC).replace(tzinfo=None)

    try:
        async with get_async_session() as session:
            # One statement decides the winner. Reading the row and then
            # deleting it would let two exchanges of the same code both
            # come away with the tokens.
            result = await session.execute(
                delete(AuthHandoff)
                .where(
                    AuthHandoff.code_hash == _lookup_hash(code),
                    AuthHandoff.expires_at > now,
                )
                .returning(AuthHandoff.id_token, AuthHandoff.refresh_token)
                .execution_options(synchronize_session=False)
            )
            row = result.first()
    except Exception:
        log.error("Failed to redeem a login handoff.", exc_info=True)
        return None

    if row is None:
        return None

    key = _seal_key(code)

    try:
        return {
            "token": decrypt_with_key(key, row[0]),
            "refresh_token": decrypt_with_key(key, row[1]) if row[1] else None,
        }
    except Exception:
        # The row was found, so the code was right; the sealed tokens not
        # opening means the stored bytes are wrong. Nothing to be done for
        # this login -- the row is already gone -- but it should be loud.
        log.error("A login handoff row could not be decrypted.", exc_info=True)
        return None


async def handoff_cleanup() -> int:
    """
    Remove handoff rows nobody came back for.

    A redeemed code deletes its own row, so this only ever sweeps logins
    that were abandoned between the provider and the landing page.

    Returns:
        int: Number of rows removed.
    """

    now = datetime.now(UTC).replace(tzinfo=None)

    async with get_async_session() as session:
        result = await session.execute(
            delete(AuthHandoff).where(AuthHandoff.expires_at <= now)
        )

    removed = result.rowcount or 0

    if removed:
        log.info(f"Removed {removed} expired login handoff rows.")

    return removed
