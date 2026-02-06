import json

from auth.client import dn_in_list, verify_client_dn
from fastapi import (
    APIRouter,
    UploadFile,
    Request,
    Depends,
    WebSocket,
    WebSocketDisconnect,
)

from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse, JSONResponse
from db.job import (
    job_get,
    job_get_next,
    job_result_save,
    job_update,
)
from db.user import (
    user_get,
    user_get_from_job,
    user_get_private_key,
    user_get_public_key,
    user_update,
    user_get_notifications,
)
from db.models import JobStatusEnum
from pathlib import Path
from utils.log import get_logger
from utils.settings import get_settings
from utils.inference_ws_manager import inference_ws_manager

from utils.crypto import (
    decrypt_data_from_file,
    deserialize_private_key_from_pem,
    deserialize_public_key_from_pem,
    encrypt_data_to_file,
    encrypt_string,
)
from utils.notifications import notifications
from utils.validators import TranscriptionJobUpdateRequest, TranscriptionResultRequest

log = get_logger()
router = APIRouter(tags=["job"])
settings = get_settings()


@router.put("/job/{job_id}", include_in_schema=False)
async def update_transcription_status(
    request: Request,
    item: TranscriptionJobUpdateRequest,
    job_id: str,
    client_dn: str = Depends(verify_client_dn),
) -> JSONResponse:
    """
    Update the status of a transcription job.

    Parameters:
        request (Request): The incoming HTTP request.
        job_id (str): The ID of the job to update.

    Returns:
        JSONResponse: The updated job status.
    """

    user_id = user_get_from_job(job_id)

    if user_id is None or job_id is None:
        raise Exception("Job or user not found: {} - {}".format(job_id, user_id))

    file_path = Path(settings.API_FILE_STORAGE_DIR) / user_id / job_id

    job = job_update(
        job_id,
        user_id,
        status=item.status,
        error=item.error,
        transcribed_seconds=item.transcribed_seconds,
    )

    if not job:
        return JSONResponse(
            content={"result": {"error": "Job not found"}}, status_code=404
        )

    if job["status"] == JobStatusEnum.COMPLETED:
        if not user_update(
            user_id,
            transcribed_seconds=item.transcribed_seconds,
            active=None,
        ):
            return JSONResponse(
                content={"result": {"error": "User not found"}}, status_code=404
            )

        if email := user_get_notifications(user_id, "job"):
            notifications.send_transcription_finished(email)
    elif job["status"] == JobStatusEnum.FAILED:
        if email := user_get_notifications(user_id, "job"):
            notifications.send_transcription_failed(email)

    # We don't want to keep files for failed or completed jobs
    # for security and storage reasons. Remove them.
    if (
        job["status"] == JobStatusEnum.FAILED
        or job["status"] == JobStatusEnum.COMPLETED
    ):
        if file_path.exists():
            file_path.unlink()

    return JSONResponse(content={"result": job})


@router.get("/job/next", include_in_schema=False)
async def get_transcription_job(
    request: Request,
    client_dn: str = Depends(verify_client_dn),
) -> JSONResponse:
    """
    Get the next available job.

    Parameters:
        request (Request): The incoming HTTP request.

    Returns:
        JSONResponse: The next available job.
    """

    return JSONResponse(content={"result": jsonable_encoder(job_get_next())})


@router.get("/job/{user_id}/{job_id}/file", include_in_schema=False)
async def get_transcription_file(
    request: Request,
    user_id: str,
    job_id: str,
    client_dn: str = Depends(verify_client_dn),
) -> StreamingResponse:
    """
    Get the data to transcribe.

    Parameters:
        request (Request): The incoming HTTP request.
        user_id (str): The ID of the user.
        job_id (str): The ID of the job.

    Returns:
        StreamingResponse: The encrypted file stream.
    """

    if not job_get(job_id, user_id):
        return JSONResponse(
            content={"result": {"error": "Job not found"}}, status_code=404
        )

    file_path = Path(settings.API_FILE_STORAGE_DIR) / user_id / job_id

    if not file_path.exists():
        return JSONResponse(
            content={"result": {"error": "File not found"}}, status_code=404
        )

    api_user = user_get(username="api_user")

    if not api_user:
        return JSONResponse(
            content={"result": {"error": "API user not found"}}, status_code=500
        )

    private_key = user_get_private_key(api_user["user_id"])
    private_key = deserialize_private_key_from_pem(
        private_key, settings.API_PRIVATE_KEY_PASSWORD
    )

    stream = decrypt_data_from_file(
        private_key,
        str(file_path),
    )

    return StreamingResponse(
        stream,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{job_id}.bin"'},
    )


@router.put("/job/{user_id}/{job_id}/file", include_in_schema=False)
async def put_video_file(
    request: Request,
    user_id: str,
    job_id: str,
    file: UploadFile,
    client_dn: str = Depends(verify_client_dn),
) -> JSONResponse:
    """
    Upload the video file to transcribe.

    Parameters:
        request (Request): The incoming HTTP request.
        user_id (str): The ID of the user.
        job_id (str): The ID of the job.
        file (UploadFile): The uploaded file.

    Returns:
        JSONResponse: The result of the upload.
    """

    filename = file.filename + ".enc"

    if not job_get(job_id, user_id):
        return JSONResponse(
            content={"result": {"error": "Job not found"}}, status_code=404
        )

    file_path = Path(settings.API_FILE_STORAGE_DIR + "/" + user_id)

    if not file_path.exists():
        file_path.mkdir(parents=True, exist_ok=True)

    file_bytes = await file.read()

    if user_id.isnumeric():
        user_id = user_get(username="api_user")["user_id"]

    public_key = user_get_public_key(user_id)
    public_key = deserialize_public_key_from_pem(public_key)

    encrypt_data_to_file(
        public_key,
        file_bytes,
        str(file_path / filename),
        chunk_size=settings.CRYPTO_CHUNK_SIZE,
    )

    return JSONResponse(
        content={
            "result": {
                "uuid": job_id,
                "user_id": user_id,
                "filename": filename,
            }
        },
        status_code=200,
    )


@router.put("/job/{user_id}/{job_id}/result", include_in_schema=False)
async def put_transcription_result(
    request: Request,
    item: TranscriptionResultRequest,
    user_id: str,
    job_id: str,
    client_dn: str = Depends(verify_client_dn),
) -> JSONResponse:
    """
    Upload the transcription result.

    Parameters:
        request (Request): The incoming HTTP request.
        user_id (str): The ID of the user.
        job_id (str): The ID of the job.

    Returns:
        JSONResponse: The result of the upload.
    """

    if not (job := job_get(job_id, user_id)):
        return JSONResponse(
            content={"result": {"error": "Job not found"}}, status_code=404
        )

    if user_id.isnumeric():
        api_user = user_get(username="api_user")["user_id"]
        public_key = user_get_public_key(api_user)
    else:
        public_key = user_get_public_key(user_id)

    public_key = deserialize_public_key_from_pem(public_key)

    match item.format:
        case "srt":
            encrypted_result = encrypt_string(public_key, item.result)
            job_result_save(
                job_id,
                user_id,
                result_srt=encrypted_result,
                external_id=job["external_id"],
            )
        case "json":
            json_str = json.dumps(item.result)
            encrypted_result = encrypt_string(public_key, json_str)
            job_result_save(
                job_id, user_id, result=encrypted_result, external_id=job["external_id"]
            )
        case "mp4":
            pass
        case _:
            return JSONResponse(
                content={"result": {"error": "Unsupported format"}}, status_code=400
            )

    job = job_update(
        job_id,
        status=JobStatusEnum.COMPLETED,
        error=None,
    )

    return JSONResponse(
        content={
            "result": {
                "uuid": job["uuid"],
                "status": job["status"],
                "job_type": job["job_type"],
            }
        }
    )


@router.websocket("/job/inference")
async def inference_worker_websocket(websocket: WebSocket):
    """
    WebSocket endpoint for inference workers to connect and receive requests.

    Workers connect here to receive inference requests from clients and send
    responses back. Authentication is done via client certificates.
    """
    # Verify client certificate
    log.info("Inference worker attempting to connect via websocket")
    client_dn = websocket.headers.get("x-client-dn", "")
    if not dn_in_list(client_dn):
        log.error(f"Invalid client certificate DN: {client_dn}")
        await websocket.close(code=4003, reason="Invalid client certificate")
        return

    await websocket.accept()
    await inference_ws_manager.connect_worker(websocket)

    try:
        while True:
            data = await websocket.receive_json()
            request_id = data.get("request_id")
            if request_id:
                inference_ws_manager.handle_response(request_id, data)
    except WebSocketDisconnect:
        inference_ws_manager.disconnect_worker(websocket)
    except Exception as e:
        log.error(f"Inference worker websocket error: {e}")
        inference_ws_manager.disconnect_worker(websocket)
