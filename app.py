import requests

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi_utils.tasks import repeat_every
from starlette.middleware.sessions import SessionMiddleware

from auth.oidc import RefreshToken, oauth, verify_user

from db.job import job_cleanup
from db.user import (
    user_create,
    user_exists,
    user_get_private_key,
    user_get_public_key,
    user_update,
    user_get,
)
from db.customer import check_quota_alerts, send_weekly_usage_reports
from db.group import check_group_quota_alerts

from fastapi.openapi.utils import get_openapi
from routers.admin import router as admin_router
from routers.external import router as external_router
from routers.healthcheck import router as healthcheck_router
from routers.job import router as job_router
from routers.transcriber import router as transcriber_router
from routers.user import router as user_router
from routers.videostream import router as videostream_router

from utils.log import get_logger
from utils.settings import get_settings

settings = get_settings()
log = get_logger()

log.info(f"Starting API: {settings.API_TITLE} {settings.API_VERSION}")

app = FastAPI(
    title=settings.API_TITLE,
    description=settings.API_DESCRIPTION,
    version=settings.API_VERSION,
    secret_key=settings.API_SECRET_KEY,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    openapi_tags=[
        {
            "name": "transcriber",
            "description": "Transcription operations",
        },
        {
            "name": "job",
            "description": "Job management operations",
        },
        {
            "name": "user",
            "description": "User management operations",
        },
        {
            "name": "external",
            "description": "External service operations",
        },
        {
            "name": "healthcheck",
            "description": "Healthcheck operations",
        },
        {
            "name": "admin",
            "description": "Administrative operations",
        },
    ],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(SessionMiddleware, settings.API_SECRET_KEY, https_only=False)
app.include_router(transcriber_router, prefix=settings.API_PREFIX, tags=["transcriber"])
app.include_router(job_router, prefix=settings.API_PREFIX, tags=["job"])
app.include_router(user_router, prefix=settings.API_PREFIX, tags=["user"])
app.include_router(videostream_router, prefix=settings.API_PREFIX, tags=["video"])
app.include_router(external_router, prefix=settings.API_PREFIX, tags=["external"])
app.include_router(healthcheck_router, prefix=settings.API_PREFIX, tags=["healthcheck"])
app.include_router(admin_router, prefix=settings.API_PREFIX, tags=["admin"])


def custom_openapi():
    """
    Custom OpenAPI schema with JWT Bearer authentication.

    Returns:
        dict: The OpenAPI schema.
    """

    if app.openapi_schema:
        return app.openapi_schema

    openapi_schema = get_openapi(
        title=settings.API_TITLE,
        version=settings.API_VERSION,
        description="JWT Authentication and Authorization",
        routes=app.routes,
    )
    openapi_schema["components"]["securitySchemes"] = {
        "BearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}
    }
    openapi_schema["security"] = [{"BearerAuth": []}]
    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi


@app.on_event("startup")
async def create_api_user() -> None:
    """
    Create the API user with RSA keypair on startup if it does not exist.

    Returns:
        None
    """

    if user_exists("api_user"):
        return

    # Create user and add RSA keypair
    user = user_create("api_user", realm="none", user_id="api_user")
    user_update(
        user["user_id"],
        encryption_password=settings.API_PRIVATE_KEY_PASSWORD,
        encryption_settings=True,
    )


@app.get("/api/auth")
async def auth(request: Request):
    """
    OIDC authentication endpoint.

    Parameters:
        request (Request): The incoming HTTP request.

    Returns:
        RedirectResponse: Redirects to the frontend with tokens.
    """

    token = await oauth.auth0.authorize_access_token(request)
    userinfo = token.get("userinfo")
    if not userinfo:
        raise ValueError("Failed to get userinfo from token")

    request.session["id_token"] = token["access_token"]

    if "refresh_token" in token:
        request.session["refresh_token"] = token["refresh_token"]

    url = f"{settings.OIDC_FRONTEND_URI}/?token={token['id_token']}"

    if "refresh_token" in token:
        url += f"&refresh_token={token['refresh_token']}"

    return RedirectResponse(url=url)


@app.get("/api/login")
async def login(request: Request):
    """
    OIDC login endpoint.

    Parameters:
        request (Request): The incoming HTTP request.

    Returns:
        RedirectResponse: Redirects to the OIDC provider for authentication.
    """

    return await oauth.auth0.authorize_redirect(request, settings.OIDC_REDIRECT_URI)


@app.get("/api/logout")
async def logout(request: Request):
    """
    OIDC logout endpoint.

    Parameters:
        request (Request): The incoming HTTP request.

    Returns:
        RedirectResponse: Redirects to the frontend after logout.
    """

    return RedirectResponse(url=settings.OIDC_FRONTEND_URI)


@app.post("/api/refresh")
async def refresh(request: Request, refresh_token: RefreshToken):
    """
    OIDC token refresh endpoint.

    Parameters:
        request (Request): The incoming HTTP request.
        refresh_token (RefreshToken): The refresh token model.

    Returns:
        JSONResponse: The new access token.
    """

    data = {
        "client_id": settings.OIDC_CLIENT_ID,
        "client_secret": settings.OIDC_CLIENT_SECRET,
        "refresh_token": refresh_token.token,
        "grant_type": "refresh_token",
    }

    try:
        response = requests.post(
            settings.OIDC_REFRESH_URI,
            data=data,
        )
        response.raise_for_status()
    except Exception:
        return JSONResponse({"error": "Failed to refresh token"}, status_code=400)

    return JSONResponse({"access_token": response.json()["access_token"]})


@app.get("/api/docs")
async def docs(request: Request) -> RedirectResponse:
    """
    Redirect to the API documentation after verifying the user.

    Parameters:
        request (Request): The incoming HTTP request.

    Returns:
        RedirectResponse: Redirects to the API documentation.
    """

    await verify_user(request)

    return RedirectResponse(url="/docs")


@app.on_event("startup")
@repeat_every(seconds=60 * 60)
def remove_old_jobs() -> None:
    """
    Periodic task to remove old jobs from the database.

    Returns:
        None
    """

    job_cleanup()


@app.on_event("startup")
def create_api_user_on_startup() -> None:
    """
    Create the API user with RSA keypair on startup if it does not exist.

    Returns:
        None
    """

    if not user_exists("api_user"):
        user = user_create("api_user", realm="none", user_id="api_user")

    user = user_get(username="api_user")

    try:
        user_get_private_key(user["user_id"])
        user_get_public_key(user["user_id"])
    except Exception:
        user_update(
            user["user_id"],
            encryption_password=settings.API_PRIVATE_KEY_PASSWORD,
            encryption_settings=True,
        )


@app.on_event("startup")
@repeat_every(seconds=60 * 60)
def check_quota_alerts_task() -> None:
    """
    Periodic task to check block quota consumption and alert admins at 95%+.

    Returns:
        None
    """

    check_quota_alerts()
    check_group_quota_alerts()


scheduler = BackgroundScheduler()
scheduler.add_job(
    send_weekly_usage_reports,
    CronTrigger(day_of_week="mon", hour=6, minute=0),
    id="send_weekly_usage_reports",
    replace_existing=True,
)


@app.on_event("startup")
def start_scheduler() -> None:
    scheduler.start()


@app.on_event("shutdown")
def stop_scheduler() -> None:
    scheduler.shutdown(wait=False)
