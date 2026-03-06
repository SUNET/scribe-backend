# Copyright (c) 2025-2026 Sunet.
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

from auth.oidc import get_current_user
from db.job import job_get
from db.user import user_get_private_key
from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pathlib import Path
from utils.crypto import (
    decrypt_data_from_file,
    deserialize_private_key_from_pem,
    get_encrypted_file_actual_size,
)
from utils.settings import get_settings
from utils.validators import VideoStreamRequestBody

router = APIRouter(tags=["video"])
settings = get_settings()
api_file_storage_dir = settings.API_FILE_STORAGE_DIR


@router.get("/transcriber/{job_id}/videostream", include_in_schema=False)
async def get_video_stream(
    request: Request,
    item: VideoStreamRequestBody,
    job_id: str,
    range: str = Header(None),
    user: dict = Depends(get_current_user),
) -> StreamingResponse:
    """
    Stream an encrypted video for a transcription job.

    Parameters:
        request (Request): The incoming HTTP request.
        job_id (str): The ID of the job.
        range (str): The byte range for streaming.
        user (dict): The current user.

    Returns:
        StreamingResponse: The video stream response.
    """

    job = job_get(job_id, user["user_id"])

    if item.encryption_password != "" and item.encryption_password is not None:
        private_key = user_get_private_key(user["user_id"])
        private_key = deserialize_private_key_from_pem(
            private_key, item.encryption_password
        )
        file_path = Path(api_file_storage_dir) / user["user_id"] / f"{job_id}.mp4.enc"
        encrypted_media = True

        if not file_path.exists():
            file_path = Path(api_file_storage_dir) / user["user_id"] / f"{job_id}.mp4"
            encrypted_media = False
    else:
        file_path = Path(api_file_storage_dir) / user["user_id"] / f"{job_id}.mp4"
        encrypted_media = False

    if not job:
        return JSONResponse({"result": {"error": "Job not found"}}, status_code=404)

    if not file_path.exists():
        return JSONResponse(
            {"result": {"error": "Video file not found"}}, status_code=404
        )

    filesize = file_path.stat().st_size

    if not range or not range.startswith("bytes="):
        range_start = 0
        range_end = filesize - 1
    else:
        range_start_str, range_end_str = range.replace("bytes=", "").split("-")
        range_start = int(range_start_str)
        range_end = int(range_end_str) if range_end_str else filesize - 1

    # Try to decrypt the first chunk of the file to verify the password
    if encrypted_media:
        try:
            decrypt_data_from_file(
                private_key,
                file_path,
                start_chunk=0,
                end_chunk=0,
            )
        except Exception:
            encrypted_media = False

    # New way to serve encrypted video files
    if encrypted_media:
        # Get the actual available file size (not the declared size)
        filesize_actual = get_encrypted_file_actual_size(
            file_path, settings.CRYPTO_CHUNK_SIZE
        )

        if filesize_actual == 0:
            return JSONResponse(
                {"result": {"error": "Encrypted file is empty or corrupted"}},
                status_code=500,
            )

        # Recalculate range_end based on actual available file size
        if not range or not range.startswith("bytes="):
            range_start = 0
            range_end = filesize_actual - 1
        else:
            range_start_str, range_end_str = range.replace("bytes=", "").split("-")
            range_start = int(range_start_str)
            range_end = int(range_end_str) if range_end_str else filesize_actual - 1

        # IMPORTANT: Clamp to actual available data
        if range_start >= filesize_actual:
            return Response(
                b"",
                status_code=416,
                headers={"Content-Range": f"bytes */{filesize_actual}"},
            )

        if range_end >= filesize_actual:
            range_end = filesize_actual - 1

        # Determine which chunks correspond to the byte range
        start_chunk = range_start // settings.CRYPTO_CHUNK_SIZE
        end_chunk = range_end // settings.CRYPTO_CHUNK_SIZE

        def stream_chunks():
            offset_in_first_chunk = range_start % settings.CRYPTO_CHUNK_SIZE
            last_chunk_bytes = (range_end % settings.CRYPTO_CHUNK_SIZE) + 1
            num_chunks = end_chunk - start_chunk + 1

            for i, chunk in enumerate(
                decrypt_data_from_file(private_key, file_path, start_chunk, end_chunk)
            ):
                chunk_start = 0
                chunk_end = len(chunk)

                if num_chunks == 1:
                    # Single chunk: apply both start and end offsets
                    chunk_start = offset_in_first_chunk
                    chunk_end = min(last_chunk_bytes, len(chunk))
                else:
                    # Multiple chunks
                    if i == 0:
                        # First chunk: start from offset
                        chunk_start = offset_in_first_chunk

                    if i == num_chunks - 1:
                        # Last chunk: end at last_chunk_bytes
                        chunk_end = min(last_chunk_bytes, len(chunk))

                # Apply both slices at once
                yield chunk[chunk_start:chunk_end]

        content_length = range_end - range_start + 1

        headers = {
            "Content-Range": f"bytes {range_start}-{range_end}/{filesize_actual}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(content_length),
        }

        return StreamingResponse(
            stream_chunks(), status_code=206, headers=headers, media_type="video/mp4"
        )

    # Old way to serve unencrypted video files
    else:
        filesize = int(file_path.stat().st_size)

        if not range or not range.startswith("bytes="):
            range_start = 0
            range_end = filesize - 1
        else:
            range_start_str, range_end_str = range.replace("bytes=", "").split("-")
            range_start = int(range_start_str)
            range_end = int(range_end_str) if range_end_str else filesize - 1

        with open(file_path, "rb") as video:
            video.seek(range_start)
            data = video.read(range_end - range_start + 1)
            headers = {
                "Content-Range": f"bytes {str(range_start)}-{str(range_end)}/{filesize}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(len(data)),
            }

            return Response(
                data, status_code=206, headers=headers, media_type="video/mp4"
            )
