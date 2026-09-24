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
Recordings made in the browser, received in parts while they are recorded.

The frontend's recorder sends a part every few seconds rather than one file
at the end: the browser deletes what the backend has confirmed, so it holds
at most the last few unsent seconds, and an hour-long lecture is already
here when it ends.  Parts are idempotent -- the same part sent twice is the
same file written twice -- so a part whose answer was lost is sent again.

Every part is encrypted as it arrives, with the api_user's public key (the
same key an uploaded file is encrypted with), and never touches the disk in
the clear.  Finishing joins the parts into two files:

- the job's input, encrypted for api_user, which the worker fetches exactly
  as it fetches an uploaded file, and which is removed when the job ends;
- the original, `<job>.orig.enc`, encrypted for the user, which only the
  user's encryption password opens.  It lives as long as the job does.

Layout, one directory per recording::

    <API_FILE_STORAGE_DIR>/<user_id>/recordings/<rid>/part-000000.enc
                                                     /part-000001.enc
                                                     /done.json

`user_id` comes from the signed-in user, never from the request; `rid` and
`seq` are validated to a fixed shape before they reach a path.
"""

import asyncio
import json
import mimetypes
import os
import re
import shutil
import tempfile
import time
from collections.abc import AsyncIterator
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import rsa

from utils.crypto import decrypt_data_from_file, encrypt_stream_to_file
from utils.settings import get_settings

settings = get_settings()

# 32 lower-case hex characters: crypto.randomUUID() without its dashes.  The
# browser names a recording before it has reached the server, so a recording
# can start with no connection at all.
RID_PATTERN = re.compile(r"^[0-9a-f]{32}$")

# 20000 parts is days of audio at any part length the recorder uses; the
# limit exists so a part number cannot make an arbitrarily long file name.
MAX_PARTS = 20000

PART_PREFIX = "part-"
PART_SUFFIX = ".enc"
DONE_FILE = "done.json"
CLAIM_DIR = ".finishing"

# A claim older than this is a finish that died half way (a restarted
# worker); it is taken over rather than blocking the recording forever.
CLAIM_STALE_SECONDS = 15 * 60

ORIGINAL_SUFFIX = ".orig.enc"

# What a recording may be, and the extension its file is given.
MIME_EXTENSIONS = {
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/mp4": ".m4a",
    "audio/mpeg": ".mp3",
    "audio/wav": ".wav",
}

UNSAFE_NAME = re.compile(r'[/\\\x00<>:"|?*\x00-\x1f\x7f]')


class RecordingError(Exception):
    """
    A request that can never succeed as sent -- a malformed id, a part too
    large.  Distinct from a missing part, which is answered by sending it.
    """


class Busy(Exception):
    """
    Another request is finishing this recording right now.
    """


def original_path(user_id: str, job_id: str) -> Path:
    """
    Where a job's original recording is kept, encrypted for its owner.
    """

    return Path(settings.API_FILE_STORAGE_DIR) / user_id / f"{job_id}{ORIGINAL_SUFFIX}"


def media_type(filename: str) -> str:
    """
    The type a recording's file is served as.  Its own table first: the
    standard library calls every .webm a video, and these never are.
    """

    for mime, extension in MIME_EXTENSIONS.items():
        if filename.lower().endswith(extension):
            return mime

    return mimetypes.guess_type(filename)[0] or "application/octet-stream"


def file_name(name: str, mime: str) -> str:
    """
    The file name a finished recording is given: the reader's own name,
    stripped of anything a file system or a header would choke on, with the
    extension its type calls for.
    """

    base_mime = (mime or "").split(";")[0].strip().lower()
    extension = MIME_EXTENSIONS.get(base_mime)

    if not extension:
        raise RecordingError("unsupported audio type")

    stem = UNSAFE_NAME.sub("", str(name or "")).strip(" .")[:120] or "Recording"

    if stem.lower().endswith(extension):
        return stem

    return stem + extension


class _StreamReader:
    """
    An async byte stream as an `async read(size)`, refusing it the moment it
    passes `limit` rather than after it has all arrived.
    """

    def __init__(self, stream: AsyncIterator[bytes], limit: int) -> None:
        self.stream = stream
        self.limit = limit
        self.buffer = bytearray()
        self.received = 0
        self.ended = False

    async def read(self, size: int) -> bytes:
        while len(self.buffer) < size and not self.ended:
            try:
                piece = await self.stream.__anext__()
            except StopAsyncIteration:
                self.ended = True
                break

            self.received += len(piece)

            if self.received > self.limit:
                raise RecordingError("part too large")

            self.buffer.extend(piece)

        out = bytes(self.buffer[:size])
        del self.buffer[:size]

        return out


class _PartsReader:
    """
    The plaintext of a recording's parts, in order, as an `async read(size)`.

    Always hands back exactly `size` bytes until the last read, so the file
    it is encrypted into has chunks of one size -- which is what reading a
    byte range back out of it relies on.
    """

    def __init__(self, private_key: rsa.RSAPrivateKey, paths: list[Path]) -> None:
        self.private_key = private_key
        self.paths = list(paths)
        self.chunks = None
        self.buffer = bytearray()

    def _next_chunk(self) -> bytes | None:
        while True:
            if self.chunks is None:
                if not self.paths:
                    return None

                self.chunks = decrypt_data_from_file(self.private_key, str(self.paths.pop(0)))

            chunk = next(self.chunks, None)

            if chunk is not None:
                return chunk

            self.chunks = None

    async def read(self, size: int) -> bytes:
        while len(self.buffer) < size:
            chunk = await asyncio.to_thread(self._next_chunk)

            if chunk is None:
                break

            self.buffer.extend(chunk)

        out = bytes(self.buffer[:size])
        del self.buffer[:size]

        return out


class Recordings:
    """
    The parts of recordings not yet made into a job.  Blocking file system
    calls go through asyncio.to_thread in the async methods, so a slow disk
    never stalls the event loop.
    """

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root if root is not None else settings.API_FILE_STORAGE_DIR)

    def _dir(self, user_id: str, rid: str) -> Path:
        if not user_id or "/" in user_id or user_id.startswith("."):
            raise RecordingError("bad user")

        if not RID_PATTERN.match(rid or ""):
            raise RecordingError("bad recording id")

        return self.root / user_id / "recordings" / rid

    @staticmethod
    def _part_name(seq: int) -> str:
        if not isinstance(seq, int) or seq < 0 or seq >= MAX_PARTS:
            raise RecordingError("bad part number")

        return f"{PART_PREFIX}{seq:06d}{PART_SUFFIX}"

    async def write_part(
        self,
        user_id: str,
        rid: str,
        seq: int,
        stream: AsyncIterator[bytes],
        public_key: rsa.RSAPublicKey,
    ) -> int:
        """
        Encrypt one part to disk as it arrives.  Written to a temporary name
        and renamed into place, so a part is either whole or absent: a crash
        half way through must never leave a short part that looks complete.

        Returns the number of plaintext bytes written.
        """

        name = self._part_name(seq)
        directory = self._dir(user_id, rid)

        if await asyncio.to_thread(self.done, user_id, rid):
            # Already a job; a late resend has nothing left to add to.
            return 0

        await asyncio.to_thread(directory.mkdir, parents=True, exist_ok=True, mode=0o700)

        fd, tmp = tempfile.mkstemp(dir=directory, prefix=".incoming-")
        os.close(fd)

        try:
            written = await encrypt_stream_to_file(
                public_key,
                _StreamReader(stream, settings.RECORDING_MAX_PART_BYTES),
                tmp,
                chunk_size=settings.CRYPTO_CHUNK_SIZE,
            )

            if written == 0:
                raise RecordingError("empty part")

            os.replace(tmp, directory / name)
        except BaseException:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass
            raise

        # A recording still being added to is not stale, whatever its
        # creation time says -- the sweep goes by the directory's mtime.
        os.utime(directory)

        return written

    def parts(self, user_id: str, rid: str) -> list[int]:
        """
        The part numbers held, in order.  Empty for a recording never seen.
        """

        directory = self._dir(user_id, rid)

        if not directory.is_dir():
            return []

        held = []

        for entry in directory.iterdir():
            name = entry.name

            if name.startswith(PART_PREFIX) and name.endswith(PART_SUFFIX):
                try:
                    held.append(int(name[len(PART_PREFIX) : -len(PART_SUFFIX)]))
                except ValueError:
                    continue

        return sorted(held)

    def missing(self, user_id: str, rid: str, count: int) -> list[int]:
        if count < 1 or count > MAX_PARTS:
            raise RecordingError("bad part count")

        held = set(self.parts(user_id, rid))

        return [seq for seq in range(count) if seq not in held]

    def done(self, user_id: str, rid: str) -> dict | None:
        """
        The job this recording became, or None.

        Kept after the parts are gone so that a finish retried after its
        answer was lost is told it already succeeded rather than creating
        the job a second time.
        """

        try:
            return json.loads((self._dir(user_id, rid) / DONE_FILE).read_text())
        except (FileNotFoundError, ValueError):
            return None

    def claim(self, user_id: str, rid: str) -> None:
        """
        Take the right to finish this recording, across every worker process
        -- a directory is created atomically or not at all.  Raises Busy
        when someone else holds it.
        """

        claim = self._dir(user_id, rid) / CLAIM_DIR

        try:
            claim.mkdir(mode=0o700)
            return
        except FileExistsError:
            pass
        except FileNotFoundError:
            raise RecordingError("nothing recorded")

        try:
            stale = time.time() - claim.stat().st_mtime > CLAIM_STALE_SECONDS
        except FileNotFoundError:
            stale = True

        if not stale:
            raise Busy()

        os.utime(claim)

    def release(self, user_id: str, rid: str) -> None:
        try:
            (self._dir(user_id, rid) / CLAIM_DIR).rmdir()
        except (FileNotFoundError, OSError):
            pass

    async def assemble(
        self,
        user_id: str,
        rid: str,
        count: int,
        private_key: rsa.RSAPrivateKey,
        outputs: list[tuple[rsa.RSAPublicKey, Path]],
    ) -> int:
        """
        Join parts 0..count-1 and encrypt the result once for each
        (public key, path) in `outputs`.  Joining is plain concatenation:
        MediaRecorder's timesliced output is one stream cut into pieces, and
        the pieces put back together are that stream.

        Each output is written to a temporary name and renamed into place.
        Returns the plaintext size.
        """

        missing = await asyncio.to_thread(self.missing, user_id, rid, count)

        if missing:
            raise RecordingError(f"{len(missing)} parts missing")

        directory = self._dir(user_id, rid)
        paths = [directory / self._part_name(seq) for seq in range(count)]
        written = 0

        for public_key, destination in outputs:
            destination.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=destination.parent, prefix=".assembling-")
            os.close(fd)

            try:
                written = await encrypt_stream_to_file(
                    public_key,
                    _PartsReader(private_key, paths),
                    tmp,
                    chunk_size=settings.CRYPTO_CHUNK_SIZE,
                )

                if written > settings.RECORDING_MAX_BYTES:
                    raise RecordingError("recording too large")

                os.replace(tmp, destination)
            except BaseException:
                try:
                    os.unlink(tmp)
                except FileNotFoundError:
                    pass
                raise

        return written

    def mark_done(self, user_id: str, rid: str, result: dict) -> None:
        """
        Record which job this became and drop the parts: once the job holds
        the audio there is no reason for a second copy of it here.
        """

        directory = self._dir(user_id, rid)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)

        tmp = directory / f".{DONE_FILE}.tmp"
        tmp.write_text(json.dumps(result))
        os.replace(tmp, directory / DONE_FILE)

        for entry in directory.iterdir():
            if entry.name == DONE_FILE:
                continue

            if entry.is_dir():
                shutil.rmtree(entry, ignore_errors=True)
            else:
                try:
                    entry.unlink()
                except FileNotFoundError:
                    pass

    def discard(self, user_id: str, rid: str) -> None:
        shutil.rmtree(self._dir(user_id, rid), ignore_errors=True)

    def sweep(self, max_age_seconds: float, now: float | None = None) -> int:
        """
        Remove recordings nobody has touched for `max_age_seconds` -- parts
        of one that was never finished, and the done marker of one that was.
        The browser keeps whatever it has not been told is here, so an
        unfinished recording removed by mistake is sent again, not lost.

        Returns how many recordings were removed.
        """

        now = time.time() if now is None else now
        removed = 0

        if not self.root.is_dir():
            return 0

        for recordings in self.root.glob("*/recordings"):
            if not recordings.is_dir():
                continue

            for directory in recordings.iterdir():
                try:
                    stale = now - directory.stat().st_mtime > max_age_seconds
                except FileNotFoundError:
                    continue

                if stale and directory.is_dir():
                    shutil.rmtree(directory, ignore_errors=True)
                    removed += 1

            try:
                recordings.rmdir()
            except OSError:
                pass

        return removed


recordings = Recordings()
