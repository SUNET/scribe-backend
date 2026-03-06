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

import os

from logging import FileHandler, Logger, getLogger


def get_logger() -> Logger:
    """
    Get the Uvicorn logger and configure it based on environment variables.

    Returns:
        Logger: Configured Uvicorn logger.
    """

    logger = getLogger("uvicorn")

    if os.environ.get("LOG_LEVEL"):
        logger.setLevel(os.environ["LOG_LEVEL"])

    if os.environ.get("LOG_FILE"):
        file_handler = FileHandler(os.environ["LOG_FILE"])
        logger.addHandler(file_handler)

    if os.environ.get("DEBUG"):
        logger.setLevel("DEBUG")

    return logger
