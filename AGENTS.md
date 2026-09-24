# Agent Guidelines — transcribe-backend

## Project overview

FastAPI backend for Sunet Scribe (transcription service). Requires Python ≥ 3.13.

## Architecture

- **Framework**: FastAPI + SQLModel + Alembic (PostgreSQL via asyncpg/psycopg2)
- **Entry point**: `app.py` — FastAPI app, OIDC auth callback, scheduler lock, startup hooks
- **Routers**: `routers/` — `admin`, `analytics`, `announcements`, `customers`, `external`, `healthcheck`, `job`, `recording`, `rules`, `transcriber`, `user`, `videostream`
- **Models**: `db/models.py` — SQLModel definitions for all tables
- **Database CRUD**: `db/` — one module per domain (`user`, `group`, `customer`, `job`, `analytics`, `announcement`, `attribute_rules`, `onboarding_attributes`)
- **DB session**: `db/session.py` — sync (`get_session`) + async (`create_async_engine`) factories. URL rewritten between `psycopg2`/`asyncpg` driver.
- **Auth**: `auth/oidc.py` — OIDC/JWT verification, `verify_token`, `verify_user(admin=...)` dependency
- **Crypto**: `utils/crypto.py` — AES-GCM + hybrid RSA, streaming encrypt/decrypt
- **Validators**: `utils/validators.py` — Pydantic v2 request models
- **Migrations**: `alembic/versions/` — chained Alembic migrations. Run `alembic heads` to find current head; do **not** record it here (changes fast).
- **Tests**: `tests/` — pytest + pytest-asyncio. Run with `.venv/bin/python -m pytest`.

## Key conventions

- Pydantic v2 (2.11+) — `BaseModel` not strict by default, type coercion works.
- SQLAlchemy objects cannot be accessed outside their session context (DetachedInstanceError). Always iterate/read inside `with get_session()` or `async with`.
- API requests from external callers omit timeout parameters by convention.
- Outbound HTTP helpers return `None` on `RequestException` and swallow errors.

## Security focus

Treat every change as a potential attack surface. Required checks for any PR:

- **Authn/Authz**: every router endpoint must depend on `verify_user` (with `admin=True` / BOFH check where appropriate). New endpoints default to authenticated; mark public ones explicitly. Realm scoping uses `_get_admin_allowed_realms()` / `_rule_realm_overlaps()` in `routers/admin.py` — reuse, don't reimplement.
- **Login handoff**: the `/api/auth` callback redirects with a one-time code, never with tokens. See *Login handoff* below; do not put anything that works as a credential in a URL.
- **JWT verification**: never trust unverified claims. Use `verify_token` from `auth/oidc.py`. Rule evaluation runs **once at login** in `/api/auth` callback — do not move it to per-request paths (perf + auth-bypass risk).
- **Session cookies**: `SessionMiddleware` is configured `https_only` outside debug, `same_site=lax`. Do not weaken. `API_SECRET_KEY` must come from settings, never hardcoded.
- **CORS**: allowlist only — current config in `app.py` derives origins from `BRANDING_*_URL` settings. Never add `allow_origins=["*"]` with `allow_credentials=True`.
- **Input validation**: all request bodies go through Pydantic v2 models in `utils/validators.py`. Reject extra fields where it matters (`model_config = ConfigDict(extra="forbid")`). Validate query/path params with typed annotations, not raw strings.
- **SQL**: use SQLModel/SQLAlchemy expressions only. No string-formatted SQL. No `.execute(text(f"..."))` with user input.
- **Crypto**: use helpers in `utils/crypto.py` (AES-GCM, hybrid RSA, streaming chunks). Never roll new primitives. Private key passphrases come from settings/secret store. Prefer `cryptography` over `pyca`-alt or custom code; treat `python-jose` as JWT-only.
- **Secrets**: never commit `.env`, `.env.real`, `dump.sql`, or `test.db`. Never log tokens, passwords, full JWTs, or encryption keys.
- **File uploads** (`routers/transcriber.py`): always stream via `encrypt_stream_to_file` with bounded `CRYPTO_CHUNK_SIZE`. Never buffer full file in memory. Validate content-type and size limits before persistence.
- **Soft-delete vs hard-delete**: `User.deleted` and `User.manually_deactivated` are load-bearing — auto-provisioning must not override admin decisions. Check before flipping flags from rule actions.
- **External HTTP**: use `httpx` with explicit timeouts on internal callers; the documented exception (external callers without timeouts) is legacy, not a pattern to copy.
- **Defensive libs to prefer**: `defusedxml` for any XML parse, `bleach` for HTML sanitization if rendering user text, `cryptography` for primitives. Avoid `pickle` on untrusted input.
- **Run semgrep before merge**: `semgrep` plugin available — use `semgrep_scan` on touched files.

## Performance focus

- **Async I/O end-to-end**: routers are `async def`; never call blocking I/O on the event loop. CPU-bound or blocking work goes to a thread (`asyncio.to_thread`) or `apscheduler` job. Upload encryption runs off the event loop (see recent commit `b78b342`).
- **DB sessions**:
  - Use the async session for request handlers; sync `get_session()` only in scripts/migrations/scheduler.
  - Keep sessions short-lived. Open inside the handler, close before returning the response.
  - Always read related objects inside the session — accessing after close raises `DetachedInstanceError`.
- **Query patterns**:
  - Avoid N+1: use `selectinload`/`joinedload` for relationships read in lists.
  - Composite indexes already exist for hot paths (`db/models.py`: `ix_jobs_user_id_created_at`, `ix_jobs_status_created_at`, `ix_group_user_link_*`, `ix_worker_health_*`, page-views composites). Reuse before adding new ones.
  - Paginate any list endpoint that can grow unbounded (jobs, users, page_views, announcements).
- **Connection pool**: tune via `create_async_engine` `pool_opts` in `db/session.py`. Don't open ad-hoc engines per request.
- **Streaming**: large responses use `StreamingResponse`; large uploads use chunked encryption. Never `await file.read()` whole.
- **Scheduler**: single-worker via file lock (`acquire_scheduler_lock` in `app.py`). Multi-process deploys rely on this — do not duplicate scheduled jobs in handler code.
- **Caching**: `cachetools` available for in-process caches (OIDC JWKS, etc.). Set TTLs; never cache per-user data process-wide.
- **Logging**: avoid f-string-evaluating expensive args in debug logs that may be filtered out — use `%`-style lazy formatting where it matters.

## Login handoff (`db/auth_handoff.py`)

How a finished OIDC login gets its tokens to the frontend. `/api/auth` used to redirect to
`{OIDC_FRONTEND_URI}/?token=<id_token>&refresh_token=<refresh_token>`, which put a working set of
credentials in the browser's history, in the referrer of everything the landing page went on to load,
and in the access log of every proxy in between. It now stores them and redirects with a one-time
code instead; the frontend's own server posts that code to `POST /api/auth/exchange` and gets the
tokens back over a connection of its own. **The browser never sees a token.** The frontend needs
`OIDC_APP_EXCHANGE_ROUTE` pointing at that endpoint — it is a new setting, so a deployment that does
not add it cannot log anyone in.

The row is in the database rather than in memory because the Dockerfile runs `--workers 8`: the
redirect lands in one process and the exchange in another, so an in-process dictionary would work
perfectly in development and fail seven times in eight in production.

Three things carry the security and none of them are decoration:

- **Redemption is one statement** — `DELETE ... RETURNING`. It is the delete that decides who won, so
  a code cannot be redeemed twice however many processes race for it, and the tokens leave the
  database at the moment they are handed over rather than waiting for a sweeper. Do not turn this
  back into a read followed by a delete.
- **The code is never stored.** What is stored is one HKDF derivation of it as the lookup handle,
  while the tokens are encrypted (`encrypt_with_key`, AES-GCM) under a second, independent derivation
  of the same code. The two labels in `db/auth_handoff.py` are what keeps them independent. A dump of
  `auth_handoff` is ciphertext without a key.
- **A login that cannot be stored is not completed.** `handoff_create()` returning `None` sends the
  reader back with `?error=login_failed`. There is no fallback to the query string — that is the
  thing being removed.

`/api/auth/exchange` is deliberately unauthenticated, because the code *is* the credential. It is
public in `tests/test_autentication.py`'s allowlist for that reason. Unknown, spent and expired all
answer the same 400, so it tells a prober nothing; there is no rate limit because there is nothing to
throttle against 256 bits of `secrets.token_urlsafe`. `AUTH_HANDOFF_TTL_SECONDS` (60) covers a
redirect and one request, not a reader who leaves the tab open. Redeemed rows delete themselves, so
`remove_expired_auth_handoffs` in `app.py` only ever sweeps logins abandoned between the provider and
the landing page.

Never log a code, a token, or the contents of one of these rows.

## Admin hierarchy

- **BOFH** (`bofh=True`): full access to all resources across all realms.
- **Realm Admin** (`admin=True`): scoped to own `realm` + `admin_domains` (comma-separated).
- Realm scoping: `_get_admin_allowed_realms()` in `routers/admin.py`.
- `_rule_realm_overlaps()` checks comma-separated realm overlap, not exact match.

## Attribute rules (`db/attribute_rules.py`)

- Rules match JWT claim values against conditions (`equals`, `contains`, `starts_with`, `ends_with`, `regex_match`, …).
- Actions: activate user, deny access, grant admin, assign to group, assign admin domains, notify on job/deletion.
- `realm` field stores comma-separated realms — filtering checks overlap, not exact match.
- `manually_deactivated` on `User` prevents auto-provisioning from overriding admin decisions.
- Rule evaluation runs **once at login** (in `/api/auth` callback in `app.py`), NOT on every API call. Keep it that way (perf + auth-decision integrity).
- `evaluate_rules()` iteration must stay inside the session context (DetachedInstanceError).
- `test_rules()` builds pseudo-JWT from stored user fields and resolves group IDs to names.
- Regex conditions: validate at write time (catastrophic-backtracking risk). Consider `safe-regex` if accepting user-supplied patterns.

## Onboarding attributes (`db/onboarding_attributes.py`)

- Reference table of known claim names (`email`, `preferred_username`, `domain`, `affiliation`, `realm`).
- Seeded on startup via `seed_default_attributes` (called from `app.py`).
- Only BOFH can add/delete attributes.

## Transcription results (`job_results`)

Three independent columns, all encrypted with the owner's public key, all written by `job_result_save()` (each argument left unset leaves that column alone):

- `result` — JSON transcription (diarized segments), uploaded with `format: "json"`
- `result_srt` — SRT subtitles, uploaded with `format: "srt"`
- `result_words` — per-word timings/confidence, uploaded with `format: "words"`

`result_words` is nullable and never backfilled: rows written before it existed stay NULL and every other read path ignores it. It is served by its own endpoint (`GET /transcriber/{job_id}/words`) rather than being folded into the transcription, because it is several times larger than the text and only the editor needs it. The endpoint returns `{"result": ""}` — not 404 — when a job has no word data, so callers treat "no word data" as normal.

Payload shape (produced by transcribe-worker `utils/words.py`, which is the authority):

```json
{"version": 1, "words": [{"t": "Hej", "s": 0.12, "e": 0.34, "c": 0.98}]}
```

Flat and time-ordered rather than nested per segment, so it survives the user re-splitting or merging captions. `c` is omitted when the worker ran with `WORD_CONFIDENCE=false`. The backend stores it opaquely — bump `version` in the worker if the shape changes, and treat an unknown version as absent.

## Recordings from the browser (`routers/recording.py`, `utils/recordings.py`)

The frontend's recorder (`/record` in scribe-ui) sends a recording **in parts while it is being recorded**, not as one upload at the end. The browser deletes each part once it has been confirmed here, so it holds at most the last few unsent seconds, and when recording stops the rest is already here.

- `PUT /recordings/{rid}/part/{seq}` — one part, encrypted to disk **as it arrives** (`encrypt_stream_to_file`, api_user's public key: the same key an uploaded file gets). Parts are never on disk in the clear. They are written to a temporary name and renamed into place, so a part is whole or absent. Sending the same part twice writes the same file twice, which is what makes resending after a lost answer safe.
- `GET /recordings/{rid}` → `{parts, done}` — what is held, so a reloaded browser sends only what is missing.
- `POST /recordings/{rid}/finish` (`RecordingFinishRequest`: `parts`, `name`, `mime`) — 409 `{"missing": [...]}` if parts are absent. Otherwise it creates the job, joins the parts and encrypts the result twice: `<job>` for api_user (the worker fetches it exactly like an upload, and it is removed when the job ends, as today) and **`<job>.orig.enc` for the user**, which only their encryption password opens. **Idempotent**: `done.json` remembers the job, so a finish repeated after a lost answer returns the same job instead of making a second one. A `.finishing` directory (created atomically, so it holds across worker processes) keeps two finishes from running at once. The second one gets 503 and retries into the `done` answer. A claim older than 15 minutes is a finish that died, and is taken over. A failed finish removes the job it made and keeps the parts.
- `DELETE /recordings/{rid}` — an unfinished recording thrown away.
- `rid` is `^[0-9a-f]{32}$`, chosen by the browser so a recording can start with no connection. The path is `<API_FILE_STORAGE_DIR>/<user_id>/recordings/<rid>/`, with `user_id` taken from the token and never from the request.
- Answers follow the recorder's retry logic: 2xx move on, 409 send the listed parts, 422 never (stop retrying), 503 later.
- `remove_abandoned_recordings` (hourly, scheduler worker only) sweeps recordings nobody has touched for `RECORDING_ABANDON_HOURS`. That includes the `done.json` of finished ones, which only needs to outlive a lost answer. The browser keeps what it has not had confirmed, so an unfinished recording swept by mistake is sent again, not lost.

**The original** is served by `POST /transcriber/{job_id}/original` (the password goes in the body, hence POST), streamed with its decrypted file name. The job listing marks it with `has_original`. It lives exactly as long as the job: `job_files_remove()` in `db/job.py` is now the one list of a job's files, used by both `job_remove()` and the 7-day `job_cleanup()`. Add any new per-job file there.

## Migrations

- Chained Alembic migrations under `alembic/versions/`.
- To find current head: `.venv/bin/alembic heads`. To inspect chain: `.venv/bin/alembic history`.
- Recent additions cover: `manually_deactivated`, `attribute_rules`, `onboarding_attributes`, `support_contact_email`, `announcements`, `manually_activated`, `worker_health`, `dark_mode`, `notify_job`/`notify_deletion` on rules, `manually_set_notifications` on users.
- New migration MUST be reproducible from scratch (`alembic upgrade head` on empty DB). See commit `af23910`.

## Testing

```bash
.venv/bin/python -m pytest
```

Suites: `test_autentication.py`, `test_auth_handoff.py`, `test_crypto.py`, `test_recordings.py`, `test_rules.py`. The process does not exit by itself after the run: `utils/notifications.py` starts a non-daemon timer thread at import. The results are printed first; run with a `timeout` in scripts. Add a test for any auth/permission/crypto change before merging.
