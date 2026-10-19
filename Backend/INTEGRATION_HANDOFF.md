# MedMind: Integration Handoff (Backend + Voice Gateway)

Status as of 2026-10-18. Read this before connecting real providers or Asterisk.

What is verified so far is **only** what the offline test suites prove: source
code plus mocked/fake clients, synthetic data, network blocked. **No real
provider (Deepgram, Hamsa, ElevenLabs, WhatsApp), no real Asterisk and no
production deployment has been tested.** See "Known limitations".

---

## 1. Two separate Python environments

The backend and the Voice Gateway use **different virtual environments**.
Do not install voice packages into the backend `.venv`, or the other way round.

| | Backend (`app/`, `agent/`) | Voice Gateway (`voice_gateway/`) |
|---|---|---|
| Folder | `Backend/.venv` | `Backend/.venv-voice` |
| Python | 3.13 | 3.13 (needs `audioop-lts`, because 3.13 removed `audioop`) |
| Runtime deps | `requirements-prod.txt` (or `requirements.txt` for dev) | `voice_gateway/requirements-voice.txt` |
| Test deps | already in the backend requirements | `voice_gateway/requirements-voice-test.txt` |
| `medmind` package | not installed: add `agent` to `PYTHONPATH` (the Dockerfile does `pip install ./agent`) | not needed |

```powershell
# Voice Gateway environment (from Backend/)
py -3.13 -m venv .venv-voice
.\.venv-voice\Scripts\python.exe -m pip install -r voice_gateway\requirements-voice-test.txt
```

`Backend/.gitignore` ignores `.venv/` but **not** `.venv-voice/`; do not commit
that folder.

The Voice Gateway loads the Silero VAD model from the file bundled in the
`silero-vad` package when `voice_gateway.main` is imported (no download).

There is **no deployment definition for the Voice Gateway yet**:
`Dockerfile.backend` packages only `app.main`. The gateway is a FastAPI app,
`voice_gateway.main:app` (WebSocket `/asterisk/media`, `GET /health`).

---

## 2. Environment variables (names and placeholders only)

Never commit real values. `.env.example` lists the backend variables; the voice
ones are below. The gateway reads `Backend/.env` (without overriding variables
already set by the host).

### Voice Gateway: required

| Variable | Placeholder / rule |
|---|---|
| `VOICE_MEDIA_SHARED_SECRET` | `<random, at least 32 characters>`; must equal Asterisk's `MEDMIND_MEDIA_TOKEN` |
| `VOICE_ALLOWED_TENANT_IDS` | `<tenant-a>,<tenant-b>`; explicit list, no wildcards |
| `MEDMIND_SERVICE_TOKEN` | `<voice_gateway token from MEDMIND_SERVICE_CREDENTIALS>` |
| `MEDMIND_BACKEND_URL` | `<backend base URL>`. The default is `http://127.0.0.1:8001`, but `run.ps1` serves on port **8000**, so set this. Use `https://` when the backend is not on the same host: the service token is sent in a header |
| `HAMSA_API_KEY` | `<Hamsa key>` (Hamsa STT primary, Hamsa TTS) |
| `DEEPGRAM_API_KEY` | `<Deepgram key>` (Deepgram live fallback STT) |
| `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID` | only when `VOICE_TTS_PROVIDER=elevenlabs` |

### Voice Gateway: optional

`VOICE_TENANT_ID` (default tenant if Asterisk sends none; must also be
allow-listed), `VOICE_MEDIA_AUTH_TIMEOUT_SECONDS` (default 10),
`VOICE_TTS_PROVIDER` (`hamsa` | `elevenlabs`), `VOICE_TTS_STREAMING`,
`VOICE_STT_LANGUAGE`, `VOICE_DEFAULT_TURN_END_GRACE_SECONDS` (default 0.20),
`VOICE_DIGIT_TURN_END_GRACE_SECONDS` (default 0.30), and the other `VOICE_*`,
`HAMSA_*` and `ELEVENLABS_*` tuning values in `voice_gateway/config.py` and the
provider modules.

### Backend (see `.env.example`)

`MEDMIND_SERVICE_CREDENTIALS` uses the format
`voice_gateway=<token>@<tenant-a>,<tenant-b>`. Each token must be unique and at
least 32 random characters, with every allowed tenant listed explicitly.
Unset or malformed: every service request is rejected with 503 (fail closed).
Plus the database, AI-model, JWT and national-ID key settings in `.env.example`.

---

## 3. Running the tests (offline)

From `Backend/`, with `MEDMIND_DB_INTEGRATION` **unset** (database tests then
skip without connecting). Keep real API keys out of the test shell.

```powershell
# Voice Gateway suite (.venv-voice): every tests/test_*.py that imports
# voice_gateway and does not import app/medmind/tests/mcp_server/rag
# (38 files as of this handoff).
$env:PYTHONDONTWRITEBYTECODE = "1"
.\.venv-voice\Scripts\python.exe -B -m pytest -p no:cacheprovider `
  tests\test_voice_log_safety.py tests\test_voice_media_websocket_auth.py `
  tests\test_voice_transcript_logging_privacy.py tests\test_name_guard.py `
  tests\test_voice_media_auth.py  # ...plus the remaining voice test files

# Backend service-auth / tenant / booking / post-call tests (.venv)
$env:PYTHONPATH = "agent"
.\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider `
  tests\test_service_auth_before_tenant_lookup.py tests\test_ai_chat_service_auth.py `
  tests\test_post_call_service_auth.py tests\test_patient_lookup_tenant_isolation.py
```

Results at handoff:
- **Voice Gateway:** 188 passed, 1 xfailed (a known bug, section 7), 0 failed (38 files).
- **Backend:** 368 passed, 0 failed (34 auth, tenant, booking and post-call files).

`tests/test_*_db.py` are opt-in integration tests. They refuse any database
except `localhost\SQLEXPRESS` / `MedMind_Audit_Final2` and roll back. Never
point them at `MedMind_Booking_DB`.

---

## 4. Logging and privacy rules

Enforced in code and by `tests/test_voice_log_safety.py` and
`tests/test_voice_transcript_logging_privacy.py`:

- **No caller speech in logs.** Final transcripts are logged as stage and
  length only; digit stages (national ID, phone) add a digit count only.
  Patient names, national IDs and phone numbers must never be logged.
- **No provider message contents.** Hamsa and Deepgram messages and errors are
  logged as shape only (`kind`, `type`, field names, sizes) plus a code.
  Helpers: `voice_gateway/log_safety.py`. Exception codes are logged only as
  integers 0-99999. Provider JSON codes are logged only as such an integer, a
  string of up to 5 digits, or an uppercase/underscore token without digits.
  **Known limit:** an all-uppercase Latin word (e.g. a name written `AHMED`)
  in a provider `code`/`type` field passes that rule. This affects log text
  only, never speech processing. Tightening it would also drop legitimate
  single-word codes (`UNAUTHORIZED`); replace the rule with an allowlist once
  Hamsa's documented error codes are verified.
- **No exception messages or tracebacks on transcript/provider paths.** These
  sites log `error_type`, `error_code`, `error_origin` (innermost frames as
  file:line), `cause_type`, `stage` and, in the transcript consumer, a
  session fingerprint. Never the message.
- **Backstop filter.** `SafeExceptionFilter` is attached to every Voice Gateway
  logger and to `uvicorn.error` (which logs exceptions that escape the
  WebSocket handler, because `asterisk_media` re-raises). Tracebacks keep
  exception types, files, line numbers and function names; every message
  becomes `<message omitted>`. Plain `logger.error(...)` text and arguments
  are not changed.
  - It is **process-local**: it is installed when `voice_gateway.main` is
    imported, i.e. in the Voice Gateway process only. uvicorn configures logging
    before importing the app (CLI, `--reload`, `--workers`), and a later
    `dictConfig`/`fileConfig` keeps logger filters. Tested by
    `test_filter_survives_uvicorn_logging_configuration`, which runs uvicorn's
    real logging configuration without starting a server.
  - It does **not** cover asyncio's unhandled-task logger (`asyncio`), Gunicorn's
    own loggers (`gunicorn.error`), other ASGI servers, child loggers that do not
    call `install_log_safety`, httpx or provider SDK loggers. Configure those
    separately if used.
- **No credentials.** The Hamsa STT key travels in the WebSocket URL query
  string (`?api_key=`); this is the existing integration and has not been
  changed. So:
  - the `websockets.client` logger is capped at WARNING, because its DEBUG
    handshake line includes the query string;
  - a connect error whose text contains the key is re-raised as a generic
    `RuntimeError` without the original chain.

  Do not lower that logger's level. Service tokens and the media secret are
  never logged.
- **Benchmark policy:** `STT_BENCHMARK_LOG_TRANSCRIPTS=true` no longer logs
  transcript text in Deepgram or Hamsa. It only adds `characters` / `words`
  metadata lines. Keep it `false` in production anyway.
- If you add a log line: log IDs, stages, counts, durations and types, never
  `transcript`, `text`, `reply`, `message`, `exc` or `url` values. The
  structural test `test_no_voice_gateway_logger_call_passes_a_raw_value` fails
  on such arguments.
- **Not covered:** logs written by other libraries (asyncio, Gunicorn, httpx,
  provider SDKs) and backend (`app/`) logging. See section 7.

---

## 5. Sessions, workers and processes

- **Backend AI chat sessions are in memory** (`app/services/ai_chat_session_registry.py`).
  Run the backend as **one worker**, or put sticky routing in front of it.
  With several workers, a voice call's session is missing on the other workers.
  Sessions are lost on restart, and idle sessions expire after
  `AI_CHAT_SESSION_IDLE_MINUTES`.
- **Voice Gateway per-call state** lives inside the WebSocket handler, so
  several gateway workers are possible. Each worker loads its own Silero model,
  and each call opens its own STT/TTS connections.
- Per-call clients are closed in the handler's `finally` block. Cleanup after
  a **rejected** connection is currently broken; see the known bug in section 7.

---

## 6. Asterisk requirements (`MEDIA_START`)

Asterisk connects to `ws://<gateway>/asterisk/media` with subprotocol
`media`. Nothing from the connection is trusted until the `MEDIA_START` text
event arrives with:

```json
{
  "event": "MEDIA_START",
  "connection_id": "<id>",
  "channel_id": "<id>",
  "channel": "<channel name>",
  "format": "slin24",
  "optimal_frame_size": 960,
  "ptime": 20,
  "channel_variables": {
    "MEDMIND_MEDIA_TOKEN": "<same value as VOICE_MEDIA_SHARED_SECRET>",
    "MEDMIND_TENANT_ID": "<allow-listed tenant>"
  }
}
```

- `format` must be **`slin24`**. `ulaw` passes authentication but the Hamsa
  primary pipeline then fails with `Hamsa primary currently requires Asterisk
  format=slin24`.
- A missing, empty or wrong token, a tenant that is not allowed, missing or
  non-object `channel_variables`, an unconfigured gateway, or no `MEDIA_START`
  within `VOICE_MEDIA_AUTH_TIMEOUT_SECONDS`: the socket is closed with code
  **1008** before any session, VAD or STT/TTS stream is created. Audio sent
  before authentication is dropped.
- Verified offline (`tests/test_voice_media_websocket_auth.py`).
  **NOT VERIFIED:** that your Asterisk version and dialplan actually put these
  channel variables into `MEDIA_START`. The repository has no dialplan or
  Asterisk configuration. Prove it in the lab (section 8, stage 2).

---

## 7. Known limitations and unresolved risks

**Confirmed (in code or by tests):**
1. **Cleanup crash on rejected connections.** The `/asterisk/media` `finally`
   block passes `tenant_id` to post-call processing for every connection, but
   `tenant_id` is only set after authentication. Each rejected or
   unauthenticated connection ends with `UnboundLocalError` after the 1008
   close. The rest of the cleanup is skipped and the error reaches the ASGI
   server. Tracked by the strict-xfail test
   `test_rejected_connection_cleanup_completes`. Not fixed.
2. **Hamsa all-digit replies are dropped.** A plain-text Hamsa reply made only
   of digits (e.g. a national ID) parses as a JSON number and is skipped as a
   non-object message, so it is never returned as a transcript
   (`hamsa_stt.py`, `transcribe`). Its log line is now safe; the parsing is
   unchanged and needs a decision.
3. **Non-object JSON on the media socket.** A text frame such as `[]` raises
   `AttributeError` in the handler. Nothing is created (fails closed), but via
   an unhandled exception rather than a clean close.
4. **Hamsa key in the URL.** The Hamsa STT key is in the URL query string, so
   it can appear in proxy or provider access logs outside this application.
   Check whether Hamsa supports header authentication.
5. **Single backend worker.** Backend AI sessions are in memory (section 5).
6. **No Voice Gateway deployment definition.** `MEDMIND_BACKEND_URL` is not in
   `.env.example`, and nothing enforces HTTPS.
7. **`/ai/debug/router` is unauthenticated** (backend, pre-existing).

**Possible (not observed):**
- Logs from asyncio ("Task exception was never retrieved"), Gunicorn, httpx
  and the provider SDKs bypass the filters. `uvicorn.error` is covered, but
  only in the Voice Gateway process and only under uvicorn; a running uvicorn
  server has not been tested.
- An all-uppercase Latin word in a provider `code`/`type` field is logged as
  a code (see section 4).
- Backend logging of received chat messages has not been audited.

**Not verified (needs live tests):**
- Real Deepgram, Hamsa and ElevenLabs connections, authentication, timeouts,
  cancellation and cleanup.
- Asterisk channel-variable delivery and real audio handling.
- WhatsApp post-call delivery.
- Behaviour under load, with several concurrent calls and several workers.

---

## 8. Real-provider integration checklist (do separately, in a lab)

Prerequisites: non-production API keys for every provider, a newly generated
`VOICE_MEDIA_SHARED_SECRET`, one test tenant, the backend on the audit database
copy only (never `MedMind_Booking_DB`), WhatsApp/n8n unset or pointed at a sink,
synthetic callers and fictional names/IDs only, and logs deleted after each run.

- [ ] **Stage 1, local endpoint, no network:** start the gateway from
      `.venv-voice`. With a local WebSocket client, repeat the rejection cases
      from section 6 and confirm 1008 closes, no outbound connections and no
      secret in the logs.
- [ ] **Stage 2, Asterisk handshake:** use a lab Asterisk with a dialplan
      setting `MEDMIND_MEDIA_TOKEN` and `MEDMIND_TENANT_ID` and `format=slin24`.
      Leave provider keys unset and confirm the call authenticates
      (`voice_tenant_selected ... source=asterisk`) and then fails safely at
      provider start-up.
- [ ] **Stage 3, backend handoff:** run the backend with one worker on the
      audit copy. Check session creation, chat, a test booking and the
      post-call confirmation (faked sink); check that the wrong tenant and the
      wrong token are rejected.
- [ ] **Stage 4, providers one at a time:** Deepgram, then Hamsa STT, Hamsa
      TTS, ElevenLabs. Check auth, barge-in cancellation, hang-up cleanup and
      timeouts. Grep the logs for any key, name, ID or phone number (expect none).
- [ ] **Stage 5, end to end:** a full synthetic call. Check the name-guard
      retry, turn timing (0.20 s normal, 0.30 s digits) and the audit-database
      changes; then reset the audit data.
- [ ] Decide on and fix known issues 1–3 (section 7) before production.
- [ ] Write a deployment definition for the gateway (process manager or
      container, `MEDMIND_BACKEND_URL` over HTTPS, single backend worker).
