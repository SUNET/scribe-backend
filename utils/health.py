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

import json
import time

from db.models import WorkerHealth
from db.session import get_session
from sqlalchemy import func


MAX_ENTRIES_PER_WORKER = 300


class HealthStatus:
    """
    Health status tracking for workers. Stores load average, memory usage, GPU
    usage, and last seen timestamp for each worker in PostgreSQL.
    """

    def add(self, data):
        """
        Add a new health status entry for a worker.

        Parameters:
            data (dict): A dictionary containing worker_id, load_avg, memory_usage, and gpu_usage.
        """

        worker_id = data.get("worker_id")
        gpu_usage = data.get("gpu_usage", 0)
        if not isinstance(gpu_usage, str):
            gpu_usage = json.dumps(gpu_usage)

        with get_session() as session:
            entry = WorkerHealth(
                worker_id=worker_id,
                load_avg=data.get("load_avg", 0),
                memory_usage=data.get("memory_usage", 0),
                gpu_usage=gpu_usage,
            )
            session.add(entry)
            session.flush()

            # Trim old entries beyond MAX_ENTRIES_PER_WORKER
            count = (
                session.query(func.count(WorkerHealth.id))
                .filter(WorkerHealth.worker_id == worker_id)
                .scalar()
            )

            if count > MAX_ENTRIES_PER_WORKER:
                excess = count - MAX_ENTRIES_PER_WORKER
                oldest_ids = (
                    session.query(WorkerHealth.id)
                    .filter(WorkerHealth.worker_id == worker_id)
                    .order_by(WorkerHealth.created_at.asc())
                    .limit(excess)
                    .subquery()
                )
                session.query(WorkerHealth).filter(
                    WorkerHealth.id.in_(oldest_ids.select())
                ).delete(synchronize_session=False)

    def get(self):
        """
        Get the health status of all workers.

        Returns:
            dict: A dictionary containing the health status of all workers.
        """

        result = {}

        with get_session() as session:
            entries = (
                session.query(WorkerHealth)
                .order_by(WorkerHealth.worker_id, WorkerHealth.created_at.asc())
                .all()
            )

            for entry in entries:
                if entry.worker_id not in result:
                    result[entry.worker_id] = []

                gpu_usage = entry.gpu_usage
                if gpu_usage is not None:
                    try:
                        gpu_usage = json.loads(gpu_usage)
                    except (json.JSONDecodeError, TypeError):
                        pass

                result[entry.worker_id].append(
                    {
                        "load_avg": entry.load_avg,
                        "memory_usage": entry.memory_usage,
                        "gpu_usage": gpu_usage,
                        "seen": entry.created_at.timestamp()
                        if entry.created_at
                        else time.time(),
                    }
                )

        return dict(sorted(result.items()))
