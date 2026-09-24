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
Recordings sent from the browser in parts: stored encrypted as they arrive,
joined into a job and an original when they end, and swept when abandoned.

The routes are driven against a FastAPI app holding only the recording
router, with the signed-in user and the database calls replaced, so nothing
here needs a real database or identity provider.
"""

import os

os.environ.setdefault("API_DATABASE_URL", "sqlite://")

import time

import httpx
import pytest
from fastapi import FastAPI

import routers.recording as recording_router
import utils.recordings as recordings_module
from auth.oidc import get_current_user
from utils.crypto import (
    decrypt_data_from_file,
    generate_rsa_keypair,
    serialize_private_key_to_pem,
    serialize_public_key_to_pem,
)
from utils.recordings import RecordingError, Recordings, file_name

USER = "user-1"
RID = "0123456789abcdef0123456789abcdef"
API_PASSWORD = "api-password"


@pytest.fixture(scope="module")
def keys():
    """
    Two key pairs -- api_user's and the user's -- made once: RSA key
    generation is the slow part of this file.
    """

    return {
        "api": generate_rsa_keypair(2048),
        "user": generate_rsa_keypair(2048),
    }


async def stream(*pieces: bytes):
    for piece in pieces:
        yield piece


def read(private_key, path) -> bytes:
    return b"".join(decrypt_data_from_file(private_key, str(path)))


# --- The store ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_part_is_never_on_disk_in_the_clear(tmp_path, keys):
    store = Recordings(tmp_path)
    private, public = keys["api"]
    audio = b"OggS" + os.urandom(5000)

    await store.write_part(USER, RID, 0, stream(audio[:100], audio[100:]), public)

    stored = next((tmp_path / USER / "recordings" / RID).glob("part-*"))

    assert audio not in stored.read_bytes()
    assert audio[:64] not in stored.read_bytes()
    assert read(private, stored) == audio
    assert store.parts(USER, RID) == [0]


@pytest.mark.asyncio
async def test_a_part_sent_twice_is_one_part(tmp_path, keys):
    store = Recordings(tmp_path)
    _, public = keys["api"]

    await store.write_part(USER, RID, 3, stream(b"abc"), public)
    await store.write_part(USER, RID, 3, stream(b"abc"), public)

    assert store.parts(USER, RID) == [3]
    assert store.missing(USER, RID, 4) == [0, 1, 2]


@pytest.mark.asyncio
async def test_a_part_that_fails_leaves_nothing_behind(tmp_path, keys, monkeypatch):
    store = Recordings(tmp_path)
    _, public = keys["api"]
    monkeypatch.setattr(recordings_module.settings, "RECORDING_MAX_PART_BYTES", 10)

    with pytest.raises(RecordingError):
        await store.write_part(USER, RID, 0, stream(b"x" * 8, b"x" * 8), public)

    with pytest.raises(RecordingError):
        await store.write_part(USER, RID, 1, stream(), public)

    assert list((tmp_path / USER / "recordings" / RID).iterdir()) == []


@pytest.mark.parametrize(
    "rid, seq",
    [("../../etc", 0), ("ABCDEF", 0), (RID + "0", 0), (RID, -1), (RID, 20000)],
)
@pytest.mark.asyncio
async def test_ids_are_checked_before_they_reach_a_path(tmp_path, keys, rid, seq):
    store = Recordings(tmp_path)

    with pytest.raises(RecordingError):
        await store.write_part(USER, rid, seq, stream(b"a"), keys["api"][1])


@pytest.mark.asyncio
async def test_assembling_joins_the_parts_for_the_job_and_for_the_owner(
    tmp_path, keys, monkeypatch
):
    # A small chunk size, so the joined file spans several chunks and the
    # parts do not line up with them.
    monkeypatch.setattr(recordings_module.settings, "CRYPTO_CHUNK_SIZE", 1000)
    store = Recordings(tmp_path)
    api_private, api_public = keys["api"]
    user_private, user_public = keys["user"]
    parts = [os.urandom(1500), os.urandom(700), os.urandom(2301)]

    for seq, data in enumerate(parts):
        await store.write_part(USER, RID, seq, stream(data), api_public)

    job_file = tmp_path / USER / "job"
    original = tmp_path / USER / "job.orig.enc"

    size = await store.assemble(
        USER, RID, 3, api_private, [(api_public, job_file), (user_public, original)]
    )

    assert size == sum(len(p) for p in parts)
    assert read(api_private, job_file) == b"".join(parts)
    assert read(user_private, original) == b"".join(parts)

    # Only the owner's key opens the original.
    with pytest.raises(ValueError):
        read(api_private, original)

    # Every chunk but the last is exactly one chunk long, which is what
    # reading a byte range back out of the file relies on.
    chunks = list(decrypt_data_from_file(user_private, str(original)))
    assert [len(c) for c in chunks] == [1000, 1000, 1000, 1000, 501]


@pytest.mark.asyncio
async def test_assembling_refuses_a_recording_with_a_gap(tmp_path, keys):
    store = Recordings(tmp_path)
    api_private, api_public = keys["api"]

    await store.write_part(USER, RID, 0, stream(b"a"), api_public)
    await store.write_part(USER, RID, 2, stream(b"c"), api_public)

    with pytest.raises(RecordingError):
        await store.assemble(USER, RID, 3, api_private, [(api_public, tmp_path / "x")])

    assert not (tmp_path / "x").exists()


@pytest.mark.asyncio
async def test_done_drops_the_parts_and_ignores_late_ones(tmp_path, keys):
    store = Recordings(tmp_path)
    _, public = keys["api"]

    await store.write_part(USER, RID, 0, stream(b"a"), public)
    store.mark_done(USER, RID, {"uuid": "job"})

    assert store.parts(USER, RID) == []
    assert store.done(USER, RID) == {"uuid": "job"}

    await store.write_part(USER, RID, 1, stream(b"b"), public)
    assert store.parts(USER, RID) == []


@pytest.mark.asyncio
async def test_only_one_finish_at_a_time(tmp_path, keys):
    store = Recordings(tmp_path)
    await store.write_part(USER, RID, 0, stream(b"a"), keys["api"][1])

    store.claim(USER, RID)

    with pytest.raises(recordings_module.Busy):
        store.claim(USER, RID)

    store.release(USER, RID)
    store.claim(USER, RID)


@pytest.mark.asyncio
async def test_a_dead_claim_is_taken_over(tmp_path, keys):
    store = Recordings(tmp_path)
    await store.write_part(USER, RID, 0, stream(b"a"), keys["api"][1])
    store.claim(USER, RID)

    claim = tmp_path / USER / "recordings" / RID / recordings_module.CLAIM_DIR
    old = time.time() - recordings_module.CLAIM_STALE_SECONDS - 1
    os.utime(claim, (old, old))

    store.claim(USER, RID)


@pytest.mark.asyncio
async def test_the_sweep_removes_only_what_nobody_touched(tmp_path, keys):
    store = Recordings(tmp_path)
    _, public = keys["api"]
    other = "f" * 32

    await store.write_part(USER, RID, 0, stream(b"a"), public)
    await store.write_part(USER, other, 0, stream(b"a"), public)

    old = time.time() - 3 * 3600
    os.utime(tmp_path / USER / "recordings" / RID, (old, old))

    assert store.sweep(2 * 3600) == 1
    assert store.parts(USER, RID) == []
    assert store.parts(USER, other) == [0]


def test_file_names_are_cleaned_and_typed():
    assert file_name("Lecture 3", "audio/webm;codecs=opus") == "Lecture 3.webm"
    assert file_name("../../x/y", "audio/ogg") == "xy.ogg"
    assert file_name("", "audio/mp4") == "Recording.m4a"
    assert file_name("a.webm", "audio/webm") == "a.webm"

    with pytest.raises(RecordingError):
        file_name("x", "text/html")


# --- The routes --------------------------------------------------------------


@pytest.fixture()
def api(tmp_path, keys, monkeypatch):
    """
    The recording router with its database calls replaced: api_user's and
    the user's keys, and jobs kept in a dict.
    """

    store = Recordings(tmp_path)
    monkeypatch.setattr(recording_router, "recordings", store)
    monkeypatch.setattr(recording_router.settings, "API_FILE_STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(recordings_module.settings, "API_FILE_STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(recording_router.settings, "API_PRIVATE_KEY_PASSWORD", API_PASSWORD)

    api_private, api_public = keys["api"]
    _, user_public = keys["user"]
    public = {
        "api": serialize_public_key_to_pem(api_public),
        USER: serialize_public_key_to_pem(user_public),
    }
    jobs = {}

    async def user_get(username=""):
        return {"user_id": "api"} if username == "api_user" else None

    async def user_get_public_key(user_id):
        return public[user_id]

    async def user_get_private_key(user_id):
        assert user_id == "api"
        return serialize_private_key_to_pem(api_private, API_PASSWORD.encode())

    async def job_create(user_id, job_type, filename):
        uuid = f"job-{len(jobs) + 1}"
        jobs[uuid] = {"uuid": uuid, "status": "uploading", "filename": filename}
        return dict(jobs[uuid])

    async def job_update(uuid, status=None, **_):
        jobs[uuid]["status"] = status

    async def job_remove(uuid):
        jobs.pop(uuid, None)

    for name, value in {
        "user_get": user_get,
        "user_get_public_key": user_get_public_key,
        "user_get_private_key": user_get_private_key,
        "job_create": job_create,
        "job_update": job_update,
        "job_remove": job_remove,
    }.items():
        monkeypatch.setattr(recording_router, name, value)

    app = FastAPI()
    app.include_router(recording_router.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: {"user_id": USER}

    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test/api/v1"
    )
    client.jobs = jobs
    client.root = tmp_path

    return client


FINISH = {"parts": 2, "name": "Lecture", "mime": "audio/webm;codecs=opus"}


@pytest.mark.asyncio
async def test_a_recording_becomes_a_job_and_an_original(api, keys):
    assert (await api.put(f"/recordings/{RID}/part/0", content=b"one")).status_code == 200
    assert (await api.put(f"/recordings/{RID}/part/1", content=b"two")).status_code == 200
    assert (await api.get(f"/recordings/{RID}")).json() == {"parts": [0, 1], "done": None}

    response = await api.post(f"/recordings/{RID}/finish", json=FINISH)

    assert response.status_code == 200
    done = response.json()["done"]
    assert done == {"uuid": "job-1", "filename": "Lecture.webm"}
    assert api.jobs["job-1"]["status"] == "uploaded"

    user_dir = api.root / USER
    assert read(keys["api"][0], user_dir / "job-1") == b"onetwo"
    assert read(keys["user"][0], user_dir / "job-1.orig.enc") == b"onetwo"
    assert not list((user_dir / "recordings" / RID).glob("part-*"))


@pytest.mark.asyncio
async def test_a_finish_repeated_does_not_make_a_second_job(api):
    await api.put(f"/recordings/{RID}/part/0", content=b"one")
    await api.put(f"/recordings/{RID}/part/1", content=b"two")

    first = await api.post(f"/recordings/{RID}/finish", json=FINISH)
    second = await api.post(f"/recordings/{RID}/finish", json=FINISH)

    assert first.json() == second.json()
    assert list(api.jobs) == ["job-1"]
    assert (await api.get(f"/recordings/{RID}")).json()["done"]["uuid"] == "job-1"


@pytest.mark.asyncio
async def test_a_finish_with_parts_missing_lists_them(api):
    await api.put(f"/recordings/{RID}/part/1", content=b"two")

    response = await api.post(f"/recordings/{RID}/finish", json=FINISH)

    assert response.status_code == 409
    assert response.json() == {"missing": [0]}
    assert api.jobs == {}


@pytest.mark.asyncio
async def test_a_finish_already_running_says_try_again(api):
    await api.put(f"/recordings/{RID}/part/0", content=b"one")
    await api.put(f"/recordings/{RID}/part/1", content=b"two")
    recording_router.recordings.claim(USER, RID)

    response = await api.post(f"/recordings/{RID}/finish", json=FINISH)

    assert response.status_code == 503
    assert api.jobs == {}


@pytest.mark.asyncio
async def test_a_failed_finish_leaves_no_job_and_keeps_the_parts(api, monkeypatch):
    await api.put(f"/recordings/{RID}/part/0", content=b"one")
    await api.put(f"/recordings/{RID}/part/1", content=b"two")

    async def broken(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(recording_router.recordings, "assemble", broken)

    response = await api.post(f"/recordings/{RID}/finish", json=FINISH)

    assert response.status_code == 503
    assert api.jobs == {}
    assert (await api.get(f"/recordings/{RID}")).json()["parts"] == [0, 1]

    # And the claim went with it, so the next try is not told to wait.
    recording_router.recordings.claim(USER, RID)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {"parts": 0, "name": "x", "mime": "audio/webm"},
        {"parts": "many", "name": "x", "mime": "audio/webm"},
        {"parts": 1, "name": "x", "mime": "text/html"},
    ],
)
async def test_a_finish_that_can_never_work_is_refused(api, body):
    await api.put(f"/recordings/{RID}/part/0", content=b"one")

    response = await api.post(f"/recordings/{RID}/finish", json=body)

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_bad_parts_are_refused(api, monkeypatch):
    assert (await api.put("/recordings/nothex/part/0", content=b"a")).status_code == 422
    assert (await api.put(f"/recordings/{RID}/part/0", content=b"")).status_code == 422

    monkeypatch.setattr(recording_router.settings, "RECORDING_MAX_PART_BYTES", 2)
    assert (await api.put(f"/recordings/{RID}/part/0", content=b"abc")).status_code == 422


@pytest.mark.asyncio
async def test_a_discarded_recording_is_gone(api):
    await api.put(f"/recordings/{RID}/part/0", content=b"one")

    assert (await api.delete(f"/recordings/{RID}")).status_code == 200
    assert (await api.get(f"/recordings/{RID}")).json() == {"parts": [], "done": None}


# --- The original's lifetime ---------------------------------------------------


def test_removing_a_job_removes_its_original(tmp_path, monkeypatch):
    import db.job

    monkeypatch.setattr(db.job.settings, "API_FILE_STORAGE_DIR", str(tmp_path))
    user_dir = tmp_path / USER
    user_dir.mkdir()

    for name in ("job", "job.mp4.enc", "job.orig.enc", "other.orig.enc"):
        (user_dir / name).write_bytes(b"x")

    db.job.job_files_remove(USER, "job")

    assert sorted(p.name for p in user_dir.iterdir()) == ["other.orig.enc"]


@pytest.mark.asyncio
async def test_the_original_is_downloaded_with_the_owners_password(tmp_path, keys, monkeypatch):
    from routers import transcriber
    from utils.crypto import encrypt_data_to_file, encrypt_string

    user_private, user_public = keys["user"]
    monkeypatch.setattr(recordings_module.settings, "API_FILE_STORAGE_DIR", str(tmp_path))
    (tmp_path / USER).mkdir()
    audio = os.urandom(3000)
    encrypt_data_to_file(user_public, audio, str(tmp_path / USER / "job-1.orig.enc"))

    async def job_get(job_id, user_id):
        if job_id == "job-1" and user_id == USER:
            return {"uuid": "job-1", "filename": encrypt_string(user_public, "Lecture 3.webm")}
        return {}

    async def user_get_private_key(user_id):
        return serialize_private_key_to_pem(user_private, b"secret")

    monkeypatch.setattr(transcriber, "job_get", job_get)
    monkeypatch.setattr(transcriber, "user_get_private_key", user_get_private_key)

    app = FastAPI()
    app.include_router(transcriber.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: {"user_id": USER}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test/api/v1"
    ) as client:
        ok = await client.post("/transcriber/job-1/original", json={"encryption_password": "secret"})
        wrong = await client.post("/transcriber/job-1/original", json={"encryption_password": "nope"})
        none = await client.post("/transcriber/job-2/original", json={"encryption_password": "secret"})

    assert ok.status_code == 200
    assert ok.content == audio
    assert ok.headers["content-type"] == "audio/webm"
    assert "Lecture%203.webm" in ok.headers["content-disposition"]
    assert wrong.status_code == 403
    assert none.status_code == 404
