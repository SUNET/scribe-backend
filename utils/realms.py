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

"""Helpers for comma-separated realm lists (User.admin_domains, Customer.realms)."""

from typing import Optional


def csv_has(value: Optional[str], item: str) -> bool:
    """
    True if `item` is a whole entry of the comma-separated `value`.

    Case-insensitive, whitespace-trimmed. Never a substring match:
    "kth.se" is not in "student.kth.se".
    """

    wanted = (item or "").strip().lower()

    return bool(wanted) and wanted in [
        d.strip().lower() for d in (value or "").split(",")
    ]
