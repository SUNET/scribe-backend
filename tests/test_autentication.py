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

import pytest
import requests

BASE_URL = "http://localhost:8000"
OPENAPI_SPEC = requests.get(f"{BASE_URL}/api/openapi.json").json()
PUBLIC_ENDPOINTS = {
    "/api/docs",
    "/api/login",
    "/api/auth",
    "/api/logout",
    "/api/refresh",
    "/api/v1/status",
}


def client_verification_disabled() -> bool:
    """
    Check if API_CLIENT_VERIFICATION_ENABLED=False in .env
    and if so, skip cetain endpoints.
    """

    try:
        with open(".env", "r") as f:
            for line in f:
                if line.strip().startswith("API_CLIENT_VERIFICATION_ENABLED"):
                    key, value = line.strip().split("=", 1)
                    return value.lower() == "false"
    except FileNotFoundError:
        pass

    return False


@pytest.mark.parametrize(
    "path,method",
    [
        (path, method.upper())
        for path, item in OPENAPI_SPEC["paths"].items()
        for method in item.keys()
    ],
)
def test_auth_required_for_all_endpoints(path, method):
    """
    Verify that all endpoints except explicitly public ones
    reject unauthenticated requests with 401 or 403.
    """

    if client_verification_disabled():
        PUBLIC_ENDPOINTS.add("/api/v1/transcriber/external")
        PUBLIC_ENDPOINTS.add("/api/v1/job")
        PUBLIC_ENDPOINTS.add("/api/v1/healthcheck")

    if any(path.startswith(pub) for pub in PUBLIC_ENDPOINTS):
        pytest.skip(f"Public endpoint: {path}")

    url = BASE_URL + path
    url = url.replace("{job_id}", "test123")
    url = url.replace("{user_id}", "user123")
    url = url.replace("{external_id}", "ext123")
    url = url.replace("{output_format}", "txt")
    url = url.replace("{group_id}", "1")
    url = url.replace("{username}", "dummy")

    kwargs = {}
    if method in ("POST", "PUT"):
        kwargs["json"] = {}

    response = requests.request(method, url, **kwargs)

    assert response.status_code in (401, 403), (
        f"Expected 401/403 for unauthenticated access to {method} {path}, "
        f"but got {response.status_code} ({response.text[:200]})"
    )
