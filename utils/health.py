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

import collections
import time


class HealthStatus:
    """
    Health status tracking for workers. Stores load average, memory usage, GPU
    usage, and last seen timestamp for each worker.
    """

    def __init__(self):
        """
        Initialize the HealthStatus with an empty dictionary of workers.
        """

        self.workers = {}

    def add(self, data):
        """
        Add a new health status entry for a worker.

        Parameters:
            data (dict): A dictionary containing worker_id, load_avg, memory_usage, and gpu_usage.
        """

        worker_id = data.get("worker_id")

        if worker_id not in self.workers:
            self.workers[worker_id] = collections.deque(maxlen=300)

        self.workers[worker_id].append(
            {
                "load_avg": data.get("load_avg", 0),
                "memory_usage": data.get("memory_usage", 0),
                "gpu_usage": data.get("gpu_usage", 0),
                "seen": time.time(),
            }
        )

    def get(self):
        """
        Get the health status of all workers.

        Returns:
            dict: A dictionary containing the health status of all workers.
        """

        result = {}
        workers = dict(sorted(self.workers.items()))

        for worker_id, stats in workers.items():
            result[worker_id] = []
            for stat in stats:
                result[worker_id].append(stat)

        return result
