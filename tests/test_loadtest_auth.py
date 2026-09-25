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
The load-test sign-in (auth/oidc.py) must be impossible to reach by accident.
"""

import pytest

from auth import oidc


@pytest.fixture
def flags(monkeypatch):
    def set_flags(loadtest: bool, debug: bool) -> None:
        monkeypatch.setattr(oidc.settings, "API_LOADTEST_AUTH", loadtest)
        monkeypatch.setattr(oidc.settings, "API_DEBUG", debug)

    return set_flags


def test_off_by_default():
    assert oidc.get_settings().model_fields["API_LOADTEST_AUTH"].default is False


@pytest.mark.parametrize("loadtest, debug", [(False, False), (False, True), (True, False)])
def test_refused_unless_both_flags_are_on(flags, loadtest, debug):
    flags(loadtest, debug)

    assert oidc.loadtest_identity("loadtest-1") is None


def test_signs_in_a_loadtest_user_in_its_own_realm(flags):
    flags(True, True)

    claims = oidc.loadtest_identity("loadtest-7")

    assert claims["sub"] == "loadtest-7"
    assert claims["realm"] == "loadtest.invalid"
    assert claims["preferred_username"] == "loadtest-7@loadtest.invalid"


@pytest.mark.parametrize(
    "token", ["loadtest-", "loadtest-../x", "loadtest-a b", "loadtest-" + "a" * 33, "eyJhbGciOi.real.jwt"]
)
def test_anything_else_goes_to_the_oidc_provider(flags, token):
    flags(True, True)

    assert oidc.loadtest_identity(token) is None
