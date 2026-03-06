# Copyright (c) 2025-2025 Sunet.
# Contributor: Kristofer Hallin
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

from fastapi import HTTPException, Header
from typing import Optional
from utils.log import get_logger
from utils.settings import get_settings

settings = get_settings()
log = get_logger()

dn_list = [settings.API_WORKER_CLIENT_DN, settings.API_KALTURA_CLIENT_DN]


def verify_client_dn(
    client_dn: Optional[str] = Header(
        default=None,
        alias=settings.API_CLIENT_VERIFICATION_HEADER,
    ),
) -> Optional[str]:
    """
    Verify the client DN from request headers.

    Parameters:
        client_dn (Optional[str]): The client DN from request headers.

    Returns:
        Optional[str]: The verified client DN.

    Raises:
        HTTPException: If the client DN is missing or invalid.
    """

    if not client_dn and settings.API_CLIENT_VERIFICATION_ENABLED:
        log.warning("Missing client DN in request headers")
        raise HTTPException(status_code=401, detail="Missing client DN")

    if client_dn not in dn_list and settings.API_CLIENT_VERIFICATION_ENABLED:
        log.warning(f"Invalid client DN: {client_dn}")
        raise HTTPException(status_code=403, detail="Invalid client DN")

    return client_dn


def dn_in_list(dn):
    """
    Check if the given DN is in the allowed DN list.

    Parameters:
        dn (str): The DN to check.

    Returns:
        bool: True if the DN is in the list, False otherwise.
    """

    # Bypass check if verification is disabled
    if settings.API_CLIENT_VERIFICATION_ENABLED is False:
        return True

    accept = dn in dn_list

    log.info(f"DN {dn} acceptance: {accept}")

    return accept
