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
already set by the host) when `voice_gateway.main` or
`voice_gateway.providers.hamsa_tts` is imported, through
`voice_gateway/config.py::load_environment`. **Exception (2026-10-22):** with
`APP_ENV=staging` in the process environment it loads no `.env` at all
(`staging_selected()`, the same rule as the backend), so every value must be
supplied explicitly. A `.env` file cannot select staging.

### Voice Gateway: required

| Variable | Placeholder / rule |
|---|---|
| `VOICE_MEDIA_SHARED_SECRET` | `<random, at least 32 characters>`; must equal Asterisk's `MEDMIND_MEDIA_TOKEN`, and must differ from every service-hop token in the gateway's environment (`MEDMIND_SERVICE_TOKEN`, `MCP_SERVER_TOKEN[_NEXT]`, `MCP_BACKEND_SERVICE_TOKEN`, any token in `MEDMIND_SERVICE_CREDENTIALS[_NEXT]`); if it equals one, every call is rejected (`shared_secret_reuses_service_token`) |
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

### AI booking chain: Agent -> MCP -> Backend (added 2026-10-21)

Two separate credentials, both sent in `X-MedMind-Service-Token`:

| Hop | Sender setting | Checked by | Mode setting |
|---|---|---|---|
| Agent (backend process) -> MCP | `MCP_SERVER_TOKEN` (backend env) | MCP server, every tool (`mcp_server/auth.py`) | `MCP_AUTH_MODE` (MCP env) |
| MCP -> Backend | `MCP_BACKEND_SERVICE_TOKEN` (MCP env) | `mcp_server` entry of `MEDMIND_SERVICE_CREDENTIALS` (`app/security/booking_auth.py`) | `BOOKING_SERVICE_AUTH_MODE` (backend env) |

- Protected backend routes (the ones the MCP tools call): `POST /appointments`,
  `/appointments/{ref}/cancel`, `/appointments/{ref}/reschedule`,
  `/appointments/lookup`, `/appointments/search-by-national-id`,
  `/patients/resolve`, `/patients/lookup`, `PATCH /patients/{id}/profile`.
  Only the `mcp_server` credential is accepted there (another gateway's valid
  token gets 403 `SERVICE_NOT_ALLOWED`), and only for its listed tenants
  (403 `SERVICE_TENANT_NOT_ALLOWED`). The token is checked before the tenant
  lookup. Catalog reads and staff routes are unchanged.
- **`mcp_server` is booking-only (2026-10-22).** The gateway routes refuse it
  with 403 `SERVICE_NOT_ALLOWED`, right after the token check and before
  any tenant lookup (`require_gateway_service`, `app/security/service_auth.py`):
  `/ai/chat`, `/ai/chat-v2`, `/ai/sessions`, `/ai/sessions/close`,
  `/ai/warmup`, `/post-call/booking-confirmation`,
  `/diagnostics/attachments`, and the development-only `/ai/debug/router`
  (still 404 outside `APP_ENV=development`). Every other configured service
  (e.g. `voice_gateway`) is a gateway service and keeps its access and
  tenant list unchanged.
- `POST /appointments/{ref}/confirm` accepts either the `mcp_server` token or
  a staff bearer token of a `provider_admin`/`receptionist` of the
  `X-Tenant-ID` provider. It has no audit mode: with neither it is always 401
  `AUTH_REQUIRED`; with both, 400 `MULTIPLE_CREDENTIALS`. The patient's
  `national_id` is still required for both. Staff confirmations are recorded
  as `changed_by=staff` with the staff user id and audited
  (`appointment.confirm`) in the same commit; the service token cannot claim
  `changed_by=staff` (403 `SERVICE_CANNOT_ACT_AS_STAFF`).
- **`audit` (default, transitional):** a request **without** the header is
  still served and logged (`booking_service_auth_missing method=... route=<template>`
  on the backend, `mcp_service_auth_missing client=<host>` on MCP). Those
  requests are **not protected**. A header that is present but wrong is
  always rejected (backend 401 `SERVICE_AUTH_INVALID`; MCP "Unauthorized MCP
  request.").
- **`enforce`:** a missing header is rejected too (backend 401
  `SERVICE_AUTH_REQUIRED`, or 503 `SERVICE_AUTH_NOT_CONFIGURED` when
  `MEDMIND_SERVICE_CREDENTIALS` is unset; MCP rejects every call when
  `MCP_SERVER_TOKEN` is unset or shorter than 32 characters). With
  `MCP_AUTH_MODE=enforce` in the backend env, the agent also refuses to start
  an MCP session without `MCP_SERVER_TOKEN`.
- Any other mode value stops the process at settings loading (no "off").
  The agent reads `MCP_AUTH_MODE` the same way (trimmed, case-insensitive,
  `audit` when absent): an empty or unknown value makes agent startup fail
  with "MCP_AUTH_MODE must be 'audit' or 'enforce'." (the value is not
  echoed). `MCP_URL` absent uses `http://127.0.0.1:9000/mcp`; set but empty
  fails with "MCP_URL is set but empty.".

**Rollout (order matters, because a present-but-unknown token is rejected even in audit mode):**

1. Generate two different random tokens of at least 32 characters, e.g.
   `python -c "import secrets; print(secrets.token_urlsafe(48))"`, and keep
   them in your secret store only.
2. **Backend first:** append `;mcp_server=<token B>@<tenant>,<tenant>` to
   `MEDMIND_SERVICE_CREDENTIALS` (the same tenants the AI gateways serve; no
   wildcards), keep `BOOKING_SERVICE_AUTH_MODE=audit`, restart. A malformed
   value makes every service route (voice included) answer 503, so check the
   AI chat still works right after the restart.
3. **MCP second:** set `MCP_BACKEND_SERVICE_TOKEN=<token B>`,
   `MCP_SERVER_TOKEN=<token A>`, `MCP_AUTH_MODE=audit`, restart the MCP server.
4. **Agent last:** set `MCP_SERVER_TOKEN=<token A>` in the backend env and
   restart the backend (agent MCP sessions are cached per tenant, so a
   restart is required).
5. **Verify both hops** with real AI traffic on a test tenant (or the smoke
   checks under "Verification tools" below, against a test database only):
   a booking, a cancel and a reschedule must succeed,
   and after the restart the logs must show **no** `mcp_service_auth_missing`
   (agent -> MCP), **no** `booking_service_auth_missing` (MCP -> backend),
   and no `mcp_service_auth_invalid`, `booking_service_not_allowed`,
   `service_tenant_denied` or 401/403 on those routes.
6. **Enforce MCP:** `MCP_AUTH_MODE=enforce` on the MCP server and in the
   backend env, restart both, repeat step 5, and run
   `python -m mcp_server.auth_negative_check` against the staging MCP: it
   must print `missing token: refused` and `wrong token: refused` (exit 0).
7. **Enforce backend:** `BOOKING_SERVICE_AUTH_MODE=enforce`, restart, repeat
   step 5, and confirm a request to `POST /api/v1/patients/lookup` without
   the header gets 401 on the test environment.
8. **Rollback:** set the affected mode back to `audit` and restart; no data
   changes are involved. Rolling back does not accept wrong tokens, so a
   token mismatch is fixed by correcting the token, not by the mode.

**Verification tools (what each one proves):**

| Check | Proves | Does not prove |
|---|---|---|
| `scripts/smoke_mcp_connection.py`, `smoke_mcp_catalog.py`, `smoke_mcp_services.py`, `smoke_mcp_available_slots.py` | script -> MCP token accepted; catalog reads work | **Not** the MCP -> backend credential: catalog routes need only `X-Tenant-ID` |
| `python -m mcp_server.patient_lookup_check` | MCP -> backend credential on a protected route: one read-only `lookup_patient` call (`POST /patients/lookup`) with a built-in non-existent ID; with `BOOKING_SERVICE_AUTH_MODE=enforce` a wrong/missing `MCP_BACKEND_SERVICE_TOKEN` makes it fail | The real agent's header (the check sends its own) |
| `python -m mcp_server.auth_negative_check` | MCP refuses a tool call without a token (enforce) and with a wrong token (both modes) | Anything about the backend hop |
| Backend/MCP logs during real AI traffic | the real agent sends its token (`mcp_service_auth_missing` absent) and MCP sends its token (`booking_service_auth_missing` absent) | - |

Rules for these checks:
- Test database only (`DB_NAME` set explicitly; the backend default is
  `MedMind_Booking_DB`). Never run the writing scripts
  (`create_reschedule_fixture.py`, `smoke_legacy_*`, `smoke_mcp_patient_resolve.py`)
  as a check; the `smoke_legacy_*` scripts also call AI providers.
- `python -m mcp_server.patient_lookup_check` (the only patient-lookup
  check for staging):
  - `TEST_EXISTING_NATIONAL_ID` must be **absent** from the process
    environment, not merely empty; if the variable exists at all the check
    prints `REFUSED` and sends nothing.
  - `MCP_URL`, `MCP_SERVER_TOKEN` and `TENANT_ID` must all be supplied
    explicitly in the process environment; it never loads `.env`.
  - `MCP_URL` must be a loopback URL (`127.0.0.1`, `localhost` or `::1`,
    numeric port, no user:password); it ignores proxy settings and does not
    follow redirects.
  - It makes exactly one read-only MCP tool call, `lookup_patient`, with a
    built-in non-existent national ID, and prints one line only:
    `found: false` (exit 0), `found: true` (exit 1, unexpected),
    `REFUSED: <reason>` (exit 2) or `FAILED: <reason>` (exit 1). It never
    prints the national ID, the response, any patient field, the URL or a
    token, and fails closed on an unexpected response.
- Do **not** use `scripts/smoke_mcp_patient_lookup.py` for staging
  verification: it loads `.env` with `override=True` and can print a
  national ID and a full patient record.
- The `smoke_mcp_*` scripts also load `.env` with `override=True`, so they
  cannot test "no token" while `.env` has `MCP_SERVER_TOKEN`; use
  `mcp_server.auth_negative_check` (it reads only `MCP_URL` and `TENANT_ID`
  from the process environment and never prints a token).
- `mcp_server/mcp_idempotency_test.py` and `mcp_http_idempotency_test.py`
  send neither `X-Tenant-ID` nor a token; they are stale and fail before
  authentication.

**MCP address and deployment (current limitation):**
- The agent and the smoke scripts read `MCP_URL` (default
  `http://127.0.0.1:9000/mcp`, `agent/medmind/service.py`).
- The MCP server itself always binds `127.0.0.1:9000`, path `/mcp`: the
  values are passed explicitly to `FastMCP(...)` in `mcp_server/server.py`,
  so `MCP_HOST`, `MCP_PORT`, `MCP_STREAMABLE_HTTP_PATH` and `FASTMCP_*` have
  no effect. DNS-rebinding protection accepts only the hosts `127.0.0.1`,
  `localhost` and `host.docker.internal` (any port).
- So `MCP_URL` must use one of those hosts and reach the MCP loopback
  listener: run the MCP server on the same host / network namespace as the
  backend. `Dockerfile.backend` does not start the MCP server, and no other
  deployment definition exists; whether `host.docker.internal` reaches a
  loopback-bound MCP server depends on the Docker setup (unverified).
  Running MCP on another host is a **deployment decision** (bind address,
  allowed hosts, TLS, network policy) and needs a code change; it is not
  configurable today.

**Staging safety (added 2026-10-21):**
- **Use only an explicitly approved staging database** (today:
  `MedMind_Audit_Final2`). Set `DB_NAME` (and `DB_SERVER`) in the process
  environment **before** starting the backend; the process environment wins
  over `.env`. A new `.env` copied from `.env.example` (e.g. by `setup.ps1`)
  holds a placeholder, not a real database name. The code default is still
  `MedMind_Booking_DB` when `DB_NAME` is absent everywhere.
- **Guard** (`app/core/db_target.py`): with `APP_ENV=staging` the backend
  refuses to start unless `DB_NAME` is set explicitly (environment or
  `.env`; the code default does not count) and is not: empty or only
  whitespace (SQL Server would use the login's default database);
  `MedMind_Booking_DB` in any letter case; the `.env.example` placeholder;
  or a value containing `;`, `=`, `{` or `}` (the name goes into the ODBC
  connection string unescaped). Errors name the reason only, never the
  value or connection string. Other `APP_ENV` values are unchanged.
- **When the guard runs:** it is the first step of the backend's startup
  (`lifespan` in `app/main.py`), before that step's
  `load_dotenv(override=True)`, the models and the first database
  connection (`warm_db_pool()`). It checks the settings object the engine
  was built from, which is read once when `app.main` is imported. That is
  **not** before every `.env` load:
  - `python run_backend.py` calls `load_dotenv()` (no override) before
    importing the app, so `.env` values for unset variables are already in
    the environment when the settings, and then the guard, read them;
  - `uvicorn app.main:app` (`run.ps1`, Docker) does not; the settings read
    the environment and `./.env` directly.
  In both cases the guard sees exactly the `DB_NAME` the engine will use.
- **Preflight, no connection:** in each process's own shell and working
  directory, the same ones that will start that process (backend: `Backend/`
  with `PYTHONPATH=agent;.`; MCP: its empty directory with `PYTHONPATH` set to
  the absolute Backend paths; see "Staging runtime procedure" below),
  `python -m app.core.preflight`. It never creates a database engine (a test runs it
  in a fresh interpreter and confirms SQLAlchemy is not even imported) and
  prints no token, password or full credential. It reports `APP_ENV`,
  `DB_SERVER`, `DB_NAME` and its source (process environment, `.env`,
  default, or unknown), the guard result, both auth modes (MCP server and
  agent view), `QWEN_PLANNER_WARMUP`, `MCP_URL`/`MCP_BACKEND_BASE_URL`
  (host and port only; a malformed URL or port is a FAIL), service names
  with tenants, and whether the voice-gateway, Agent -> MCP and MCP ->
  backend tokens are set, at least 32 characters, matched between sender
  and receiver, and distinct. The Agent -> MCP check applies the MCP
  server's own rules (`mcp_server/auth.py`): an invalid
  `MCP_SERVER_TOKEN_NEXT` makes MCP reject every token and is a FAIL.
  It also checks tenants: every `VOICE_ALLOWED_TENANT_IDS` entry must be in
  the `voice_gateway` credential, and, when MCP sends its token, every
  tenant accepted on `/ai/chat` (any service except `mcp_server`) must be
  in the `mcp_server` credential; otherwise those calls get 403
  `SERVICE_TENANT_NOT_ALLOWED`. A missing voice-gateway token is always a
  FAIL (`/ai/chat` has no audit mode); missing MCP-hop tokens are warnings
  in audit mode and failures in enforce mode. Exit code 0 =
  `RESULT: VALID`; 1 = invalid. Start nothing unless it is valid and shows
  the approved `DB_NAME`.
- **Preflight scope:** it reads only the environment of the shell it runs
  in and `./.env` (in staging, `APP_ENV=staging` in the process environment,
  it reads no `.env` at all and prints `.env: ignored`). It does not see a voice gateway, MCP server or backend
  started elsewhere or with a different environment; those must be checked
  where they run. It does not verify database reachability, the MCP
  server's real listener, or AI providers.
- **`QWEN_PLANNER_WARMUP=false`** for staging checks that must not contact
  Groq at backend startup. It skips only the best-effort `models.list`
  warm-up; the planner is unchanged. Default `true`; only `true`/`false`
  are accepted. It is read once with the other backend settings (process
  environment first, then `./.env`), unlike the other `QWEN_*` values,
  which startup reads after `load_dotenv(override=True)` (`.env` first).
  Kept this way on purpose: a shell `false` cannot be undone by a `.env`
  `true`, and the preflight reports the value startup will use. Startup
  still needs non-empty `OPENAI_API_KEY` and
  `GROQ_API_KEY` (client construction makes no network call). Loading the
  local embedding models may contact the HuggingFace hub unless they are
  cached and `HF_HUB_OFFLINE=1` is set (not verified).
- **MCP server:** start `python -m mcp_server.http_server` on the same host
  as the backend, from a **separate empty working directory with no `.env`**
  (the MCP settings read `./.env` from the directory the process starts in,
  so starting it from `Backend/` would load `Backend/.env`; that is not
  safe for staging). It always listens on `127.0.0.1:9000/mcp` (loopback
  only; see "MCP address and deployment" above). Set `MCP_BACKEND_BASE_URL`
  to the backend's real port (`run_backend.py` defaults to 8004, `run.ps1`
  uses 8000, Docker 8001; the preflight warns on a mismatch with
  `APP_PORT`). The exact staging commands are under "Staging runtime
  procedure" below.
- **Warning:** `POST /api/v1/ai/chat` (and anything that uses the agent)
  still calls AI providers (OpenAI/Groq). Never use it for offline or
  no-external-call validation; use `mcp_server.auth_negative_check` and
  `mcp_server.patient_lookup_check` (rules above) instead.

**Staging runtime procedure (STAGING ONLY, added 2026-10-22):**

These instructions are for the isolated staging exercise only, never for
production. All `<...>` values are test-only placeholders generated for the
exercise; never put real tokens, keys, national IDs or values copied from a
real `.env` here, and never target `MedMind_Booking_DB`.

- **No `.env` in staging.** With `APP_ENV=staging` set in the process
  environment, the backend loads no `.env` file at all: `run_backend.py`
  skips its `load_dotenv()`, startup skips `load_dotenv(override=True)`, the
  settings are built without `.env`, and the agent skips its load
  (`staging_selected()` in `app/core/config.py`). Every value below must
  therefore be supplied explicitly in each process environment. The MCP
  server is not covered by that rule: it is protected only by starting it
  from an empty directory.
- **Backend environment** (PowerShell, in the backend shell; the process
  must be started from `Backend/`, because `run_backend.py` imports itself):

  ```powershell
  Set-Location "<absolute path to Backend>"
  Remove-Item Env:N8N_WHATSAPP_WEBHOOK_URL, Env:TEST_EXISTING_NATIONAL_ID, Env:MEDMIND_DB_INTEGRATION -ErrorAction SilentlyContinue
  $env:APP_ENV = "staging"
  $env:APP_HOST = "127.0.0.1"; $env:APP_PORT = "8001"
  $env:DB_SERVER = "localhost\SQLEXPRESS"; $env:DB_NAME = "MedMind_Audit_Final2"; $env:DB_TRUSTED_CONNECTION = "true"
  $env:BOOKING_SERVICE_AUTH_MODE = "audit"; $env:MCP_AUTH_MODE = "audit"
  $env:QWEN_PLANNER_WARMUP = "false"; $env:HF_HUB_OFFLINE = "1"; $env:TRANSFORMERS_OFFLINE = "1"
  $env:PYTHONPATH = "agent;."
  $env:MEDMIND_SERVICE_CREDENTIALS = "voice_gateway=<test voice token>@<tenant>;mcp_server=<test MCP->backend token>@<tenant>"
  $env:MCP_SERVER_TOKEN = "<test agent->MCP token>"; $env:MCP_URL = "http://127.0.0.1:9000/mcp"
  $env:JWT_SECRET_KEY = "<test-only, 48+ random characters>"
  $env:NATIONAL_ID_HASH_KEY = "<test-only, 32+ random bytes>"
  $env:NATIONAL_ID_ENCRYPTION_KEY = "<freshly generated Fernet key>"
  $env:OPENAI_API_KEY = "placeholder-not-a-key"; $env:GROQ_API_KEY = "placeholder-not-a-key"
  # For the backend preflight only (no voice gateway is started):
  $env:MEDMIND_SERVICE_TOKEN = "<same test voice token>"; $env:VOICE_ALLOWED_TENANT_IDS = "<tenant>"
  $env:MCP_BACKEND_SERVICE_TOKEN = "<same test MCP->backend token>"; $env:MCP_BACKEND_BASE_URL = "http://127.0.0.1:8001"
  & "<absolute path to Backend>\.venv\Scripts\python.exe" -B -m app.core.preflight   # must print RESULT: VALID
  & "<absolute path to Backend>\.venv\Scripts\python.exe" -B run_backend.py          # only after RESULT: VALID
  ```

  The three tokens must be different, each at least 32 characters. A
  test-only `NATIONAL_ID_HASH_KEY` also means no stored patient can match a
  lookup.
- **MCP environment** (PowerShell, in a second shell, from a separate empty
  directory that contains no `.env`):

  ```powershell
  Set-Location "<an empty directory with no .env>"
  Remove-Item Env:TEST_EXISTING_NATIONAL_ID -ErrorAction SilentlyContinue
  $env:APP_ENV = "staging"
  $env:PYTHONPATH = "<absolute path to Backend>\agent;<absolute path to Backend>"
  $env:MCP_SERVER_TOKEN = "<same test agent->MCP token>"
  $env:MCP_BACKEND_SERVICE_TOKEN = "<same test MCP->backend token>"
  $env:MCP_AUTH_MODE = "audit"
  $env:MCP_BACKEND_BASE_URL = "http://127.0.0.1:8001"
  # Tenant configuration: the MCP server has no tenant list of its own; the
  # tenant comes from each caller's X-Tenant-ID and the backend checks it
  # against the mcp_server credential. Set the same backend-side values here
  # so this shell's preflight can check the whole chain:
  $env:DB_SERVER = "localhost\SQLEXPRESS"; $env:DB_NAME = "MedMind_Audit_Final2"; $env:DB_TRUSTED_CONNECTION = "true"
  $env:BOOKING_SERVICE_AUTH_MODE = "audit"; $env:QWEN_PLANNER_WARMUP = "false"; $env:APP_PORT = "8001"
  $env:MEDMIND_SERVICE_CREDENTIALS = "<same value as the backend shell>"
  $env:MEDMIND_SERVICE_TOKEN = "<same test voice token>"; $env:VOICE_ALLOWED_TENANT_IDS = "<tenant>"
  $env:MCP_URL = "http://127.0.0.1:9000/mcp"
  & "<absolute path to Backend>\.venv\Scripts\python.exe" -B -m app.core.preflight   # must print RESULT: VALID
  & "<absolute path to Backend>\.venv\Scripts\python.exe" -B -m mcp_server.http_server   # binds 127.0.0.1:9000
  ```

  Never start the MCP server from `Backend/` for staging. Every path in
  these examples is quoted and run with the `&` call operator because the
  repository path contains spaces and parentheses.
- **Check shell** (PowerShell, a third shell, because the MCP server
  occupies its own; from a separate directory that contains no `.env`; run
  only after the MCP server is up):

  ```powershell
  Set-Location "<a directory with no .env>"
  Remove-Item Env:TEST_EXISTING_NATIONAL_ID -ErrorAction SilentlyContinue
  $env:PYTHONPATH = "<absolute path to Backend>\agent;<absolute path to Backend>"
  $env:MCP_URL = "http://127.0.0.1:9000/mcp"
  $env:MCP_SERVER_TOKEN = "<same test agent->MCP token>"
  $env:TENANT_ID = "<tenant>"
  & "<absolute path to Backend>\.venv\Scripts\python.exe" -B -m mcp_server.auth_negative_check
  #   audit mode: expect "missing token: SERVED (expected only in audit mode)"
  #   and "wrong token: refused", exit code 1
  & "<absolute path to Backend>\.venv\Scripts\python.exe" -B -m mcp_server.patient_lookup_check
  #   expect "found: false", exit code 0 ("REFUSED: ..." exit 2 means a
  #   required variable is missing or TEST_EXISTING_NATIONAL_ID still exists)
  ```

  These two are the only MCP checks for staging. `TEST_EXISTING_NATIONAL_ID`
  must be absent from this process, not merely empty.
- **Required order:**
  1. Run the preflight (`app.core.preflight`, with the quoted call-operator
     commands above) in **each** process environment (backend shell and MCP
     shell, each from its own working directory) and
     require `RESULT: VALID`; it must show `.env: ignored`,
     `DB_NAME: MedMind_Audit_Final2` and both modes `audit`. Do not paste
     its output anywhere public.
  2. Start the backend only after its preflight passes.
  3. Perform only the approved loopback checks against the backend:
     `GET http://127.0.0.1:8001/health/live` (expect `{"status": "ok"}`),
     `GET http://127.0.0.1:8001/health` (expect `"database": "connected"`),
     and the tenant check `GET http://127.0.0.1:8001/api/v1/providers/current`
     with header `X-Tenant-ID: <tenant>` (provider metadata only, no
     patient data).
  4. Start the MCP server only after those backend checks pass.
  5. Run only the two MCP checks, from the **check shell** above:
     `mcp_server.auth_negative_check` (audit mode: expect
     `missing token: SERVED`, `wrong token: refused`, exit 1) and
     `mcp_server.patient_lookup_check` (expect `found: false`, exit 0).
  6. Do not call `/ai/chat`, do not run migrations, SQL scripts or database
     tests, and do not use `scripts/smoke_mcp_patient_lookup.py` or any
     other `scripts/smoke_*` tool.
  7. Stop the MCP server and then the backend with Ctrl+C, and run only the
     previously approved read-only residue checks (`SELECT DB_NAME()` must be
     `MedMind_Audit_Final2`, then SELECT-only counts; no deletes or updates).
- **Unverified facts; failing safely is expected:**
  - The embedding models `Omartificial-Intelligence-Space/GATE-AraBert-v1`
    and `BAAI/bge-m3` are loaded at startup. With `HF_HUB_OFFLINE=1` and
    `TRANSFORMERS_OFFLINE=1` they must already be in the local cache, which
    has **not** been verified; if they are missing, backend startup fails
    safely. Do not turn the offline flags off to let them download.
  - Whether `clinic-001` is **active** has **not** been verified (it exists
    in `MedMind_Audit_Final2`, per the last DB run). If the tenant check in
    step 3 returns 404:
    1. Stop. Stop the MCP server if it was started, then the backend
       (Ctrl+C).
    2. Reconfirm the database target is `MedMind_Audit_Final2` (both
       shells' `DB_NAME`, and the preflight output).
    3. Choose only a tenant already proven active by existing evidence:
       `clinic-002` or `clinic-003`, which the DB acceptance tests resolve
       through `X-Tenant-ID`.
    4. Replace `<tenant>` with that one tenant **everywhere**, identically:
       both `@<tenant>` entries in `MEDMIND_SERVICE_CREDENTIALS` in the
       backend shell **and** the MCP shell (keep the two values identical),
       `VOICE_ALLOWED_TENANT_IDS` in both shells, `TENANT_ID` in the check
       shell, and the `X-Tenant-ID` header of the step 3 tenant check.
    5. Re-run the preflight in the backend shell and in the MCP shell; both
       must print `RESULT: VALID`. Then restart in the documented order,
       beginning again at step 2.

**Environment precedence for the auth chain (fixed 2026-10-21):**
- Keys: `MCP_URL`, `MCP_SERVER_TOKEN`, `MCP_SERVER_TOKEN_NEXT`,
  `MCP_AUTH_MODE`, `MCP_BACKEND_SERVICE_TOKEN`,
  `MEDMIND_SERVICE_CREDENTIALS`, `MEDMIND_SERVICE_CREDENTIALS_NEXT`,
  `BOOKING_SERVICE_AUTH_MODE` (`agent/medmind/env_precedence.py`).
- Rule: **a value set in the process environment always wins; `.env` only
  fills keys the environment does not set.** The backend settings, the MCP
  server and the agent now all follow it, so they use the same value.
- How: the backend lifespan (`app/main.py`) and the agent
  (`MedMindService.create`) still call `load_dotenv(override=True)`, but
  inside `keep_process_auth_settings()`, which puts back any of those keys
  that were already set. A conflict is logged as
  `env_precedence_conflict key=<name> kept=process_environment` (the name
  only, never a value).
- An empty value in the environment counts as set and is kept. For
  `MCP_SERVER_TOKEN` the agent treats it as missing (fails in enforce mode);
  an empty `MCP_AUTH_MODE` or `MCP_URL` makes agent startup fail with a clear
  configuration error.
- If loading `.env` fails, the error still propagates (startup fails), the
  keys that were set before are restored, and keys that were unset keep
  whatever was loaded before the failure.
- Values are fixed at process start: editing `.env` while running does not
  change these keys; restart, as for every other auth change.
- Unchanged: every other key (AI provider keys, model names, ...) keeps the
  previous behaviour, where `.env` overrides the environment at backend
  start and agent creation. The `scripts/smoke_*` tools still load `.env`
  with override for all keys.
- Still recommended: set each value in one place only.

**Token rotation with an overlap (added 2026-10-21).** Each receiving side
has one optional "next" slot; senders always send a single token:

| Hop | Receiver: current / next | Sender |
|---|---|---|
| Agent -> MCP | MCP env `MCP_SERVER_TOKEN` / `MCP_SERVER_TOKEN_NEXT` | backend env `MCP_SERVER_TOKEN` |
| MCP -> Backend | backend env `MEDMIND_SERVICE_CREDENTIALS` / `MEDMIND_SERVICE_CREDENTIALS_NEXT` | MCP env `MCP_BACKEND_SERVICE_TOKEN` |

Rules enforced by the code (any violation = fail closed: backend 503
`SERVICE_AUTH_NOT_CONFIGURED`, MCP rejects every call):
- A `MEDMIND_SERVICE_CREDENTIALS_NEXT` entry must name a service already in
  `MEDMIND_SERVICE_CREDENTIALS` and list **exactly** the same tenants; it may
  not reuse another service's token; at least 32 characters, no wildcards.
  Both tokens give the same identity and tenants. It works for
  `voice_gateway` too.
- `MCP_SERVER_TOKEN_NEXT` must be at least 32 characters.
- No token may serve both hops: the backend refuses a service token equal to
  `MCP_SERVER_TOKEN`/`MCP_SERVER_TOKEN_NEXT`, and MCP refuses an inbound token
  equal to `MCP_BACKEND_SERVICE_TOKEN`.
- Any other token is rejected in audit and enforce mode; an empty `*_NEXT`
  means no rotation. There is no time-based expiry: the overlap lasts until
  the `*_NEXT` value is removed and the receiver restarted.

Procedure for one hop (MCP -> Backend shown; Agent -> MCP is the same with
the variables from the table):

1. Generate a new random token (32+ characters), different from every other
   token.
2. **Receiver, open the overlap:** set
   `MEDMIND_SERVICE_CREDENTIALS_NEXT=mcp_server=<new>@<same tenants>`, restart
   the backend. Check it still answers the old token (a booking works) and
   that no `medmind_service_credentials_invalid` is logged.
3. **Sender, switch:** set `MCP_BACKEND_SERVICE_TOKEN=<new>`, restart the MCP
   server.
4. **Verify the switch:** after a booking, the backend logs
   `service_auth_next_token_used service=mcp_server` (MCP side:
   `mcp_service_auth_next_token_used`) and no `SERVICE_AUTH_INVALID`/401.
   Every running sender must have restarted; while any request still arrives
   with the old token, do not close the overlap.
5. **Receiver, promote and close:** put `<new>` in the `mcp_server` entry of
   `MEDMIND_SERVICE_CREDENTIALS`, empty `MEDMIND_SERVICE_CREDENTIALS_NEXT`,
   restart. The old token is now rejected (401 `SERVICE_AUTH_INVALID`);
   confirm a booking still works and the `next_token_used` lines stop.
6. **Rollback** before step 5: point the sender back at the old token; the
   receiver still accepts it. After step 5 the old token is gone, so a
   rollback means repeating the rotation.

With one shared `.env` for the backend and MCP (Agent -> MCP hop), step 3
sets `MCP_SERVER_TOKEN=<new>` while `MCP_SERVER_TOKEN_NEXT=<new>` is still
set; that is accepted (same token). Restart only the backend in step 3, and
in step 5 empty `MCP_SERVER_TOKEN_NEXT` and restart the MCP server.

### Catalog API contract (2026-10-22)

Catalog reads need only `X-Tenant-ID` (no service or staff token); the two
public provider routes need no tenant at all.

- `GET /api/v1/providers` (same handler as `/api/v1/public/providers`):
  `org_type` is **optional**. Omitted, it lists every publicly visible
  provider (`clinic`, `hospital`, `diagnostic_lab`; verified and active
  only; pharmacies are never listed). Supplied, it must be one of those
  three, otherwise 422. Examples: `GET /api/v1/providers`,
  `GET /api/v1/providers?org_type=hospital`.
- `GET /api/v1/providers/{provider_id}/branches` (same handler as
  `/api/v1/public/providers/{provider_id}/branches`): unchanged.
- `GET /api/v1/services`: `service_type` is optional; when supplied it must
  be one of `consultation`, `follow_up`, `teleconsultation`, `procedure`,
  `surgery`, `diagnostic` (the values the database accepts), otherwise 422.
  A valid type with no matching service returns `200 []`.
- `GET /api/v1/doctors/{doctor_id}/availability`: `date_from` is required,
  `date_to` defaults to `date_from`; a reversed range or one of 15 days or
  more is 422 `INVALID_DATE_RANGE`; `limit` is 1-200 (default 100). Past
  dates are **not** rejected: any slot on those dates still marked
  `available` is returned (booking it is rejected as `PAST_SLOT`).
- **Doctor verification:** with the default `DOCTOR_VERIFICATION_ENFORCED=false`
  doctors are listed and bookable when active, whatever their
  `verification_status` (unchanged behavior). With `true` they must be active
  **and** `verified` (see "Doctor verification" below).

### Doctor verification (2026-10-22)

**Lifecycle** (existing statuses only; `app/services/admin_catalog_service.py`,
`VERIFICATION_TRANSITIONS`):

| From | Action | To |
|---|---|---|
| `pending` | verify | `verified` |
| `pending` | reject (reason required) | `rejected` |
| `verified` | reject (reason required) | `rejected` |
| `rejected` | resubmit | `pending` |

- Repeating an approval (`verified` + verify) or a resubmission (`pending` +
  resubmit) is a **200 no-op**: nothing is changed, recorded or audited.
- Every other combination (e.g. `rejected` + verify, `rejected` + reject,
  `verified` + resubmit) is **409 `DOCTOR_VERIFICATION_CONFLICT`**, as is a
  status that changed concurrently (the update is conditional on the status
  that was read).
- New doctors start `pending`. Changing `is_active`,
  `accepting_new_patients` or `consultation_fee` never resets the status.

**Endpoints** (provider_admin of the `X-Tenant-ID` provider only; any
provider_admin of that provider, including the doctor's creator):

- `POST /api/v1/admin/doctors/{doctor_id}/verification`
  - approve: `{"decision": "verified"}` (a `reason` is rejected with 422)
  - reject: `{"decision": "rejected", "reason": "..."}`; the reason is
    trimmed and must be 1-500 UTF-16 code units (as `NVARCHAR(500)` counts
    them: an emoji counts as 2), otherwise 422
- `POST /api/v1/admin/doctors/{doctor_id}/resubmit` (no body)
- Response: the existing `AdminDoctorOut` (no reason in it). Another
  provider's or a missing doctor: 404 `DOCTOR_NOT_FOUND`; other roles: 403;
  no token: 401.

**Storage and audit:**

- Table `doctor_verification_decisions` (migration `c3d9e6a2f8b1`,
  **applied on `MedMind_Audit_Final2` only**, 2026-10-23; not applied to
  any other database, including `MedMind_Booking_DB`): one row per real
  transition with `decision` (`verified`/`rejected`/`resubmitted`),
  `previous_status`, `reason`
  (rejections only), `reviewer_user_id`, `reviewer_membership_id` and
  `decided_at`. Rows are only ever added. Composite foreign keys make the
  database reject a decision about another provider's doctor
  (`(doctor_id, provider_id)` to `doctors`) and require the reviewer's
  membership, user and provider to be one and the same membership row
  (`(reviewer_membership_id, reviewer_user_id, provider_id)` to
  `provider_memberships (id, user_id, provider_id)`, a unique key the
  migration adds). No names, licence numbers or other doctor data are
  stored.
- The status update, the decision row and a `staff_audit_logs` row
  (`doctor.verify`, `doctor.reject` or `doctor.resubmit`, resource = doctor
  id, no reason text) are written in **one commit**; any failure rolls all
  three back.
- The verification endpoints need the migration. It is applied on
  `MedMind_Audit_Final2` only. On any database without it, the endpoints
  fail on the missing table.
- On `MedMind_Audit_Final2`, the services (reject, resubmit, verify, with
  their decision and audit rows) ran in the database tests. They ran only
  inside rolled-back transactions, so nothing was ever committed. The
  endpoints have not been called over HTTP or against a running
  application.

**Bookability (`app/repositories/doctor_eligibility.py`), only when
`DOCTOR_VERIFICATION_ENFORCED=true`:** active + `verified` is required in
`GET /doctors` and the MCP `list_doctors` tool, `GET
/doctors/{id}/availability` (404 otherwise), `GET /slots` and the MCP
`list_available_slots` tool, `GET /search/doctors` and `GET
/search/availability`, and `GET /services?specialty_id=`. That last one
lists a service while at least one eligible doctor of the specialty offers
it. Booking (`POST /appointments`) and rescheduling onto a doctor who is
not verified return **409 `DOCTOR_NOT_BOOKABLE`** before any write,
independently of the catalog. Lab slots without a doctor are unaffected.
Working hours and slot generation stay allowed for pending doctors.
`GET /services` without `specialty_id` never joins doctors, so lab and
`service_type` listings are unaffected.

**Booking-time lock:** the booking check reads the doctor's status
`WITH (HOLDLOCK, ROWLOCK)` (`AppointmentRepository.doctor_is_verified`).
This is a shared lock held until the booking or rescheduling transaction
ends.

- **The race it prevents:** a booking passes the check, a rejection of
  that doctor commits, and then the booking commits anyway.
- **What happens instead:** a rejection's conditional `UPDATE` waits for
  in-flight bookings of that doctor. A booking that starts during an
  uncommitted rejection waits for it, then reads the result.
- **Bookings of the same doctor do not block each other:** the locks are
  shared, not `UPDLOCK`.
- **Assumptions:**
  - The check runs after the slot lock and before any write.
  - Each request is one transaction with one commit.
  - The hint forces a locking read whether or not
    `READ_COMMITTED_SNAPSHOT` is on.
- **When it applies:** only with enforcement on. With the flag off the
  check is skipped.
- **Lock timeout:** there is none in production, so a rejection waits as
  long as an in-flight booking takes.

**Known limitation:** `GET /services?doctor_id=` checks only that the
doctor-service link is active. It does not check the doctor's own
`is_active` or `verification_status`, with or without enforcement, so an
inactive or unverified doctor's linked services are still listed. Booking
such a doctor is still refused: an inactive doctor fails the branch check,
and an unverified one gets 409 `DOCTOR_NOT_BOOKABLE` when enforcement is
on. Whether this filter should apply the eligibility rule is an open
product decision; the code is unchanged.

**Existing appointments** of a doctor who is later rejected are **not**
cancelled or changed; they need administrative review. Only new bookings
and rescheduling onto that doctor are refused.

**Status (2026-10-23), on `MedMind_Audit_Final2` only:**

- Step 1 is done: the read-only report ran successfully.
- Step 2 is done: migration `c3d9e6a2f8b1` was applied successfully, and
  the post-migration verification passed. That covered the table, its
  columns, keys, foreign keys, check constraints and index, and
  `uq_provider_memberships_id_user_provider`. Existing data was unchanged.
- `alembic_version` now reports `c3d9e6a2f8b1`.
- `DOCTOR_VERIFICATION_ENFORCED` remains `false`, so enforcement is not
  enabled. Steps 3 and 4 have not been started.
- `MedMind_Booking_DB` was not touched; no migration has been applied to
  it.

**Concurrency verification (2026-10-23), `MedMind_Audit_Final2` only:**

`tests/test_doctor_verification_concurrency_db.py` ran with
`MEDMIND_DB_INTEGRATION=1`, `APP_ENV=staging` and explicit `DB_*`
settings: **10 passed**. Every transaction was rolled back. Read-only
snapshots before and after the run were identical: the revision, the
isolation options, and the row counts and checksums of 12 tables.

- **Isolation:** `READ_COMMITTED_SNAPSHOT` and `ALLOW_SNAPSHOT_ISOLATION`
  are **OFF** on that database.
- **What proves the HOLDLOCK fix:**
  - the test where the booking's status read blocks a rejection until the
    booking ends (lock timeout 1222, then the rejection succeeds);
  - the two stress tests. They assert that at least one rejection was
    issued while a booking held the doctor and waited for it, and that no
    booking and rejection held the doctor at the same time.
- **Limits of the two "uncommitted rejection" tests:** they prove the hint
  only when RCSI is on. With RCSI off, a plain read waits too, so they pass
  with or without `HOLDLOCK`.
- **Not tested:**
  - a rejection that is **committed** before a booking. Every rejection
    was rolled back, and testing this needs a disposable copy of the
    database;
  - rescheduling at the database level (covered by offline tests only);
  - the race with deactivating a doctor. The `is_active` check
    (`doctor_branch_is_valid`) is still a plain read.
- **Seed slots expire:** the service-flow tests need committed future slots
  from the local date + 2 days. The seeded slots end on **2026-10-26**, so
  from 2026-10-25 those three tests skip until new slots are generated.
  Generating them is a write and needs separate approval.

The steps below are separate; each needs its own approval and none implies
the next.

**Step 1 - review the read-only report** (`Database_latest/08_doctor_verification_status_report.sql`):

- Run it on `MedMind_Audit_Final2` only. First confirm the connection:
  `SELECT DB_NAME();` must return `MedMind_Audit_Final2`.
- Run the **whole** script, **never a partial selection**: its database
  guard (`IF DB_NAME() <> N'MedMind_Audit_Final2'` then `SET NOEXEC ON`)
  only protects a full run; a highlighted selection skips it.
- Recommended command, from the repository root (`-C` trusts the local SQL
  Express certificate, which ODBC Driver 18 otherwise rejects; `-I` sets
  `QUOTED_IDENTIFIER ON`, without which section 2 fails with Msg 1934;
  `-b` stops at the first error; `-d` fixes the database):

  ```powershell
  sqlcmd -S localhost\SQLEXPRESS -E -C -I -b -d MedMind_Audit_Final2 -i "Database_latest\08_doctor_verification_status_report.sql"
  ```

- It stops if a required table or column is missing. It reports: the
  alembic version; the unique keys on `doctors` and `provider_memberships`
  and whether the migration prerequisites hold (`doctors (id, provider_id)`
  present, `uq_provider_memberships_id_user_provider` not yet present); the
  verification check constraint, found by its definition; doctors per
  provider by status; active doctors that enforcement would hide; and their
  future available slots and future pending/confirmed appointments (dates
  compared with the SQL Server's local date). Counts and metadata only.

**Step 2 - apply the migration** `c3d9e6a2f8b1`, only after the report shows
the prerequisites, on `MedMind_Audit_Final2` only. `migrations/env.py` now
refuses to run (online or `--sql` offline) unless `APP_ENV=staging` is set
in the process environment and `DB_NAME` passes the staging guard
(`ensure_safe_migration_target` in `app/core/db_target.py`): no `.env` is
read, `MedMind_Booking_DB` and a missing `DB_NAME` are refused.

```powershell
$env:APP_ENV = "staging"
$env:DB_SERVER = "localhost\SQLEXPRESS"; $env:DB_NAME = "MedMind_Audit_Final2"; $env:DB_TRUSTED_CONNECTION = "true"
& "<absolute path to Backend>\.venv\Scripts\python.exe" -m alembic upgrade c3d9e6a2f8b1
```

It adds `uq_provider_memberships_id_user_provider (id, user_id, provider_id)`
(always satisfiable: `id` is the key) and the decision table, in one
transaction. The downgrade removes the table (and all decision history),
then that key. Production (`MedMind_Booking_DB`) migrations are outside
this procedure and need a separately approved change.

**Step 3 - review doctors** through the verification endpoints; nothing is
bulk-updated or auto-approved.

**Step 4 - enable enforcement**, only after the report and the reviews are
approved: `DOCTOR_VERIFICATION_ENFORCED=true` in the backend environment
(only `true`/`false` accepted), then restart the backend. Rollback: set it
to `false` and restart.

---

## 3. Running the tests (offline)

From `Backend/`, with `MEDMIND_DB_INTEGRATION` **unset** (database tests then
skip without connecting). Keep real API keys out of the test shell.

```powershell
# Voice Gateway suite (.venv-voice): every tests/test_*.py that imports
# voice_gateway and does not import app/medmind/tests/mcp_server/rag
# (40 files as of 2026-10-22).
# APP_ENV=staging is required: importing voice_gateway.main (most of these
# files do) otherwise loads Backend/.env into the test process by absolute
# path, so running from another directory does not prevent it.
$env:APP_ENV = "staging"
$env:PYTHONDONTWRITEBYTECODE = "1"
.\.venv-voice\Scripts\python.exe -B -m pytest -p no:cacheprovider `
  tests\test_voice_log_safety.py tests\test_voice_media_websocket_auth.py `
  tests\test_voice_transcript_logging_privacy.py tests\test_name_guard.py `
  tests\test_voice_media_auth.py  # ...plus the remaining voice test files

# Backend service-auth / tenant / booking / post-call tests (.venv)
$env:PYTHONPATH = "agent"
.\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider `
  tests\test_service_auth_before_tenant_lookup.py tests\test_ai_chat_service_auth.py `
  tests\test_post_call_service_auth.py tests\test_patient_lookup_tenant_isolation.py `
  tests\test_booking_service_auth.py tests\test_mcp_service_auth.py
```

Results:
- **Voice Gateway (2026-10-22):** 275 passed, 0 xfailed, 0 failed (40 files),
  run with `APP_ENV=staging`, from an empty directory, with a test-only guard
  that blocks `load_dotenv` and outbound connections and recorded 0 attempts
  of either. The former strict-xfail test now passes as a regression test
  (section 7). **Known intermittent failure (test harness, not product
  code):** the post-call tests in `tests/test_voice_media_websocket_auth.py`
  (e.g. `test_authenticated_call_dispatches_the_armed_booking_once_with_the_verified_tenant`)
  can fail when they run after a slow test. Starlette's `TestClient` cancels
  the app task as soon as the WebSocket context exits, which can interrupt the
  server's post-call cleanup before the assertion. Reproduced on the code from
  before 2026-10-22 as well; a rerun passes. Not fixed.
- **Backend (at handoff):** 368 passed, 0 failed (34 auth, tenant, booking and post-call files).

`tests/test_*_db.py` are opt-in integration tests. They refuse any database
except `localhost\SQLEXPRESS` / `MedMind_Audit_Final2` and roll back. Never
point them at `MedMind_Booking_DB`.

`tests/test_doctor_verification_concurrency_db.py` has extra rules:

- It also requires `APP_ENV=staging` and fails closed without it.
- Every connection is checked against the approved target before connecting
  and with `SELECT DB_NAME()` after.
- It uses only committed seed rows, never commits, and discards each
  connection after its outer rollback.
- It turns `DOCTOR_VERIFICATION_ENFORCED` on inside the test process only,
  and restores it afterwards.
- Run it with no backend, MCP server or agent connected to that database.

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
  non-object `channel_variables`, an unconfigured gateway (including a media
  secret equal to a service-hop token, `shared_secret_reuses_service_token`),
  or no `MEDIA_START` within `VOICE_MEDIA_AUTH_TIMEOUT_SECONDS`: the socket is
  closed with code **1008** before any session, VAD or STT/TTS stream is
  created. Audio sent before authentication is dropped.
- A text frame whose JSON is not an object (`[]`, a number, a string, `null`)
  is closed with **1008** too (2026-10-22): before authentication it is
  logged as `media_auth_rejected reason=non_object_control_message`, after
  authentication as `asterisk_control_rejected
  reason=non_object_control_message` (that call then ends with its normal
  cleanup). Text that is not valid JSON is still logged and skipped, as before.
- **Verified offline only** (`tests/test_voice_media_auth.py`,
  `tests/test_voice_media_websocket_auth.py`,
  `tests/test_voice_media_secret_separation.py`): the real `/asterisk/media`
  endpoint runs in-process through Starlette's `TestClient`, with every
  provider replaced by a recorder (no server, no socket, no Asterisk). A real
  uvicorn server with a real WebSocket client is **not** verified (section 8,
  stage 1).
  **NOT VERIFIED:** that your Asterisk version and dialplan actually put these
  channel variables into `MEDIA_START`. The repository has no dialplan or
  Asterisk configuration. Prove it in the lab (section 8, stage 2).

---

## 7. Known limitations and unresolved risks

**Confirmed (in code or by tests):**
1. ~~Cleanup crash on rejected connections~~ Fixed: post-call processing
   runs only `if media_authorization is not None`, with the tenant verified
   by `authorize_media_start()`, so a rejected or unauthenticated connection
   no longer raises `UnboundLocalError` during cleanup.
   `test_rejected_connection_cleanup_completes` is now a passing regression
   test (no xfail remains).
2. **Hamsa all-digit replies are dropped.** A plain-text Hamsa reply made only
   of digits (e.g. a national ID) parses as a JSON number and is skipped as a
   non-object message, so it is never returned as a transcript
   (`hamsa_stt.py`, `transcribe`). Its log line is now safe; the parsing is
   unchanged and needs a decision.
3. ~~Non-object JSON on the media socket~~ Fixed 2026-10-22: a text frame
   such as `[]` is now closed with 1008 (section 6) instead of raising
   `AttributeError`; covered by
   `test_non_object_json_before_media_start_is_closed_with_1008_and_starts_nothing`
   and `test_non_object_json_after_authentication_closes_the_call_with_1008`.
4. **Hamsa key in the URL.** The Hamsa STT key is in the URL query string, so
   it can appear in proxy or provider access logs outside this application.
   Check whether Hamsa supports header authentication.
5. **Single backend worker.** Backend AI sessions are in memory (section 5).
6. **No Voice Gateway deployment definition.** `MEDMIND_BACKEND_URL` is not in
   `.env.example`, and nothing enforces HTTPS.
7. ~~`/ai/debug/router` is unauthenticated~~ Fixed 2026-10-19: it returns 404 unless
   `APP_ENV=development` and always requires the trusted-service token.
8. **AI booking chain is only fully protected in `enforce` mode.** Until
   `MCP_AUTH_MODE` and `BOOKING_SERVICE_AUTH_MODE` are both `enforce`
   (section 2), a request without a token still reaches the MCP tools and the
   booking/patient routes with only `X-Tenant-ID`, as before 2026-10-21.
   `Dockerfile.backend` listens on `0.0.0.0:8001`, so keep the backend off
   public networks until then.
9. **Doctor verification is implemented but not enabled** (section 2,
   "Doctor verification"). On `MedMind_Audit_Final2` only (2026-10-23):
   - the status report ran successfully;
   - migration `c3d9e6a2f8b1` was applied and verified;
   - the report showed `CK_doctors_verification_status` present, enabled
     and trusted;
   - all 39 doctors are `verified` (28 active, 11 inactive), so turning
     enforcement on would hide no doctor, future slot or appointment there.

   Every other database is unverified, including `MedMind_Booking_DB`.
   `DOCTOR_VERIFICATION_ENFORCED` remains `false`. Until it is separately
   approved, unverified doctors still appear in `GET /doctors` and
   availability and can be booked. The verification endpoints have not been
   called against a running application.
   The booking lock (`HOLDLOCK`) passed the concurrency database tests on
   `MedMind_Audit_Final2`, inside rolled-back transactions (see
   "Concurrency verification" in section 2).

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
      `.venv-voice` with `APP_ENV=staging` in the process environment (so
      `Backend/.env` is not loaded) and every value set explicitly, bound to
      `127.0.0.1`. With a local WebSocket client, repeat the rejection cases
      from section 6 and confirm 1008 closes, no outbound connections and no
      secret in the logs. Send no valid `MEDIA_START`: an accepted call starts
      the STT/TTS pipeline and contacts the providers. Not yet run.
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
