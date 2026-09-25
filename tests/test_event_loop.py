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
Every route runs on the event loop, so blocking work called straight from an
async function stalls every other request the worker is serving. These are
static guards over the calls that have already been moved off it.
"""

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Blocking calls that must not appear directly in an async function. Each has
# an async counterpart or belongs in asyncio.to_thread:
#   deserialize_private_key_from_pem -> load_private_key (~0.2 s of CPU)
#   generate_rsa_keypair, validate_private_key_password -> asyncio.to_thread
#   encrypt_data_to_file, job_files_remove -> asyncio.to_thread
#   get_session -> get_async_session
#   notification_sent_record_* -> the *_async methods
BLOCKING = {
    "deserialize_private_key_from_pem",
    "generate_rsa_keypair",
    "validate_private_key_password",
    "encrypt_data_to_file",
    "job_files_remove",
    "get_session",
    "notification_sent_record_add",
    "notification_sent_record_exists",
    "open",
}


def application_files():
    for path in sorted(ROOT.rglob("*.py")):
        relative = path.relative_to(ROOT)

        if relative.parts[0] in {"tests", "alembic", ".venv", "scripts"}:
            continue

        yield relative, ast.parse(path.read_text())


def direct_calls(function: ast.AsyncFunctionDef):
    """
    Calls made by the function itself, not by functions defined inside it
    (which run wherever they are handed to, typically a thread).
    """

    stack = list(ast.iter_child_nodes(function))

    while stack:
        node = stack.pop()

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue

        if isinstance(node, ast.Call):
            yield node

        stack.extend(ast.iter_child_nodes(node))


def test_no_blocking_calls_in_async_functions():
    offenders = []

    for relative, tree in application_files():
        for function in ast.walk(tree):
            if not isinstance(function, ast.AsyncFunctionDef):
                continue

            for call in direct_calls(function):
                func = call.func
                name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)

                # aiofiles.open is the async one; only the builtin blocks.
                if name == "open" and not isinstance(func, ast.Name):
                    continue

                if name in BLOCKING:
                    offenders.append(f"{relative}:{call.lineno} {name}() in {function.name}")

    assert offenders == [], "blocking call on the event loop: " + ", ".join(offenders)
