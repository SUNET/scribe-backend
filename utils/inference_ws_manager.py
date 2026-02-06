import asyncio
from fastapi import WebSocket
from utils.log import get_logger

log = get_logger()


class InferenceWSManager:
    """Manager for inference worker WebSocket connections."""

    def __init__(self):
        self.workers: list[WebSocket] = []
        self.pending_requests: dict[str, asyncio.Future] = {}
        self._worker_index = 0

    async def connect_worker(self, ws: WebSocket):
        """Register a worker connection."""
        self.workers.append(ws)
        log.info(f"Inference worker connected. Total workers: {len(self.workers)}")

    def disconnect_worker(self, ws: WebSocket):
        """Remove a worker connection."""
        if ws in self.workers:
            self.workers.remove(ws)
        log.info(f"Inference worker disconnected. Total workers: {len(self.workers)}")

    def get_worker(self) -> WebSocket | None:
        """Get next available worker (round-robin)."""
        if not self.workers:
            return None
        worker = self.workers[self._worker_index % len(self.workers)]
        self._worker_index += 1
        return worker

    async def send_request(self, request_id: str, payload: dict) -> dict:
        """Send inference request to a worker and wait for response."""
        worker = self.get_worker()
        if not worker:
            raise RuntimeError("No inference workers available")

        future = asyncio.get_event_loop().create_future()
        self.pending_requests[request_id] = future

        try:
            await worker.send_json({"request_id": request_id, **payload})
            return await asyncio.wait_for(future, timeout=600.0)
        except asyncio.TimeoutError:
            raise RuntimeError("Inference request timed out")
        finally:
            self.pending_requests.pop(request_id, None)

    def handle_response(self, request_id: str, response: dict):
        """Handle response from worker."""
        if request_id in self.pending_requests:
            self.pending_requests[request_id].set_result(response)


inference_ws_manager = InferenceWSManager()
