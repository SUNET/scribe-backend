import time

from auth.client import verify_client_dn
from auth.oidc import get_current_admin_user
from db.session import get_session
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from utils.health import HealthStatus

router = APIRouter(tags=["healthcheck"])
health = HealthStatus()


@router.post("/healthcheck", include_in_schema=False)
async def healthcheck(
    request: Request,
    client_dn: str = Depends(verify_client_dn),
) -> JSONResponse:
    """
    Recevice a JSON blob with system data from the GPU workers.

    Parameters:
        request (Request): The incoming HTTP request.

    Returns:
        JSONResponse: The result of the health check.
    """

    data = await request.json()

    health.add(data)

    return JSONResponse(content={"result": "ok"})


@router.get("/healthcheck", include_in_schema=False)
async def get_healthcheck(
    request: Request,
    admin_user: dict = Depends(get_current_admin_user),
) -> JSONResponse:
    """
    Get the health status of all workers.

    Parameters:
        request (Request): The incoming HTTP request.
        user_id (str): The ID of the user.

    Returns:
        JSONResponse: The health status of all workers.
    """

    if not admin_user["bofh"]:
        return JSONResponse(
            content={"error": "User not authorized"},
            status_code=403,
        )

    data = health.get()

    return JSONResponse(content={"result": data})


@router.get("/status")
async def get_status() -> JSONResponse:
    """
    Public status endpoint to check if backend, database, and workers are working.
    No authentication required - intended for monitoring tools.

    Returns:
        JSONResponse: Status of backend, database, and worker connectivity.
    """

    status = {
        "backend": "ok",
        "database": "ok",
        "workers": "error",
        "workers_online": 0,
    }

    # Check database connectivity
    try:
        with get_session() as session:
            session.execute(text("SELECT 1"))
    except Exception:
        status["database"] = "error"

    # Check worker status - worker is online if seen within last 2 minutes
    now = time.time()
    online_count = 0
    worker_data = health.get()

    for worker_id, stats in worker_data.items():
        if stats:
            last_seen = stats[-1].get("seen", 0)
            if now - last_seen < 120:
                online_count += 1

    status["workers_online"] = online_count
    if online_count > 0:
        status["workers"] = "ok"

    # Determine overall status (workers not critical for basic health)
    core_ok = status["backend"] == "ok" and status["database"] == "ok"
    status_code = 200 if core_ok else 503

    return JSONResponse(content=status, status_code=status_code)
