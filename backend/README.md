# Taasheera backend — traveler authentication

The backend supports traveler registration, email/password and Google sign-in, a protected profile, refresh, logout, password reset, and authenticated passport upload and extraction. The frontend connects the authentication flows and traveler profile. There is no admin registration.

## Windows setup and run

Install Python 3.12 or newer. From the repository root in PowerShell, run this setup once after cloning:

```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.lock
.\.venv\Scripts\python.exe dev.py setup
```

On every later start, run from `backend/`:

```powershell
.\.venv\Scripts\python.exe dev.py run
```

`dev.py setup` creates `backend/.env.local` once with a private JWT signing secret; it never prints or replaces that secret. To use the passport assistant locally, add a line `GEMINI_API_KEY=<key>` to that same file (get a free key at https://aistudio.google.com, or ask the team for the shared test key privately). Never put the key in a tracked file: this repository is public. `dev.py run` automatically reads it and the public `GOOGLE_CLIENT_ID` in the tracked `backend/.env.development`, then starts Uvicorn on `http://127.0.0.1:8000` with local HTTP cookies. No virtual environment activation or PowerShell execution-policy change is needed. If `py` is unavailable, use the full path to your installed Python for the first command.

The local secret stays stable across restarts and is Git-ignored. The development launcher loads only these local settings; production startup still reads environment variables and must receive its own `JWT_SECRET`, `GOOGLE_CLIENT_ID`, and secure-cookie settings from deployment configuration. Never commit a production secret or Google Client Secret. Changing the JWT secret invalidates existing access JWTs; persisted refresh sessions still work until revoked or expired.

Open http://127.0.0.1:8000/docs to try registration. Stop the server with Ctrl+C. For a run-only environment, install `requirements.lock` instead of `requirements-dev.lock`.

Run the tests from `backend/` (CI installs `requirements-dev.lock`):

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Tests use isolated temporary SQLite databases and never the development database.
They generate their own signing secrets and require no developer secrets.

## Migration and container checks

Local `dev.py run` keeps `SCHEMA_AUTO_CREATE=true` so existing developer databases continue to
work. A deployed process defaults to `SCHEMA_AUTO_CREATE=false` and refuses to start until the
Alembic schema revision is current. Before starting a new image, run `python migrate.py upgrade`
against its `DATABASE_URL`; `python migrate.py status` reports the current and required revisions.
The upgrade command creates a fresh schema. It can also stamp an unversioned database only when
its schema exactly matches the committed models; it refuses mismatched schemas and never discards
traveler data. Back up an existing database before its first migration. Do not run migrations
independently in every API replica.

From the repository root, build the image with `docker build -t taasheera-backend backend`.
It includes Tesseract and a font, runs as a non-root user, and has a Docker health check. Its
`/health/live` endpoint checks the process; `/health/ready` checks the database, Alembic revision,
and Tesseract when required. The image expects `APP_ENV=production`, an explicit `DATABASE_URL`,
`JWT_SECRET`, an exact HTTPS `AUTH_ALLOWED_ORIGINS`, and secure cookies. Supply a durable private
mount or storage adapter for passports and activity logs. The image does not bundle `.env` files.
See `docs/DEPLOYMENT_PLAN.md` for the remaining hosting-dependent work.

Each API response includes a server-generated `X-Request-ID`. Structured request logs contain only
that ID, HTTP method, route template, response status, and duration. They exclude the raw URL,
query string, headers, request body, traveler fields, passport IDs, and credentials. The provided
local launcher and container disable Uvicorn's separate raw-path access log; keep it disabled if
the deployment host overrides the server command.

## Passport API

The main app mounts `POST /passports`, `GET /passports/{id}/image`,
`POST /passports/{id}/extract`, and `GET`/`PUT /passports/{id}/review`. Each needs the same bearer access token as `/auth/me`;
the upload ID is resolved only within the authenticated traveler's folder. The local
storage default is `backend/storage/passports/` (ignored by Git). Set
`PASSPORT_STORAGE_DIR` to use another local directory. A private bucket adapter is
still needed before production deployment. Install the Tesseract executable to run
OCR outside tests.

Set `PASSPORT_UPLOADS_ENABLED=false` on a host without durable private file storage.
The free Render blueprint does this; it runs the existing API for registration and sign-in only.

## Activity audit

`ActivityEvent` links each server-timestamped event to a traveler. The backend records successful
registration, known-account email/password sign-in successes and failures, verified Google sign-ins,
logout, and passport upload/extraction outcomes. `POST /activity/events` accepts only a bearer token,
an allowlisted `page_visit` or `click`, a fixed page/control identifier, and a matching outcome;
the traveler ID comes from the token, not the request body. It returns `204` and rejects extra fields.
No request bodies, URLs, passport IDs, OCR results, email addresses, credentials, or free text enter
activity records.

The SQLModel table is authoritative. A matching JSONL entry is appended to
`backend/storage/activity-logs/<traveler_id>/<UTC-date>.jsonl`, which is ignored by Git and not
served by FastAPI. Set `ACTIVITY_LOG_DIR` to an absolute private directory to move it. File creation
requests owner-only permissions where supported. If the JSONL mirror cannot be written, the database
event remains and the server emits a generic error line; the completed traveler action is not undone.
Back up and restrict both the database and JSONL directory in deployment. The initial Alembic
revision includes this table; local development still uses `create_all` for convenience.

Anonymous clicks, duplicate-email registration attempts, unknown-email sign-in failures, invalid
Google credentials, and failed Google account collisions have no verified traveler owner, so they are
not stored. Browser activity requests are best effort; failed delivery is not queued for later retry.

## Login and session API

| Endpoint | Input | Success |
| --- | --- | --- |
| `POST /auth/login` | JSON `email`, `password` | `200`: `access_token`, `token_type: bearer`, `expires_in`; sets refresh cookie |
| `GET /auth/me` | `Authorization: Bearer <access_token>` | `200`: `id`, `name`, `email` |
| `POST /auth/refresh` | Refresh cookie, no JSON body or access token required | `200`: new access token and rotated refresh cookie |
| `POST /auth/logout` | Refresh cookie, no JSON body required | `204`: session revoked and cookie cleared; safe to repeat |

Unknown emails and incorrect passwords return the same `401` message, `Invalid email or password.` Unknown emails still undergo bcrypt verification against a dummy hash. Request validation errors remain `422` and omit submitted values. Access tokens use HS256 with a fixed algorithm allowlist, issuer/audience checks, and required identity, session, issue-time and expiry claims. JWTs last at most 15 minutes. `/auth/me` accepts only a bearer access token, never just a cookie.

Refresh tokens contain 32 random bytes and are stored only as SHA-256 hashes. Their host-only `taasheera_refresh` cookie has `HttpOnly`, `SameSite=Strict`, and `Path=/auth`. `Secure` defaults to true; set `AUTH_COOKIE_SECURE=false` only for local HTTP. Responses containing tokens or profile data use `Cache-Control: no-store`.

A session expires seven days after login; rotation does not extend that deadline. Each refresh atomically replaces the current token. Reusing an older token revokes the entire session, including the replacement and all of its access tokens. Clients must serialize refresh requests, including across tabs: concurrent use of one cookie triggers this replay protection. Logout also immediately invalidates that session's access tokens through a database session check. Other independent device sessions remain valid. Re-login with an existing refresh cookie revokes the replaced browser session.

Cookie-changing endpoints check an incoming `Origin` against `AUTH_ALLOWED_ORIGINS`, a comma-separated exact allowlist. Defaults are `http://127.0.0.1:5173,http://127.0.0.1:8000`. Requests without an Origin are accepted for API clients unless marked cross-site by `Sec-Fetch-Site`. Configure exact HTTPS origins for deployment. This is CSRF protection, not a CORS allowance; no CORS middleware was added. The Vite development proxy forwards `/auth` to the backend on the same browser origin.

For a manual backend check, open http://127.0.0.1:8000/docs after starting with the environment above. Register a traveler, call login, copy only the returned access token into **Authorize**, then call `/auth/me`. Swagger/browser keeps the refresh cookie for refresh and logout. After logout, the old access token must return `401`. See `frontend/README.md` for the browser sign-in checklist.

## Google sign-in

`POST /auth/google` accepts JSON `{"id_token":"<Google Identity Services credential>"}`. The frontend sends the **ID token** from the GIS JavaScript callback, not a Google API access token or authorization code. The endpoint is a same-origin JSON API, not Google's direct HTML form/redirect callback.

The backend uses `google.oauth2.id_token.verify_oauth2_token` from the supported `google-auth` library to verify the signature, configured audience, issuer, and expiry. It additionally requires `email_verified: true`, a valid email, and a nonempty string `sub`. Google certificates are fetched over HTTPS with a 10-second request timeout; provider transport failures return `503`. Tokens and verifier exception details are not logged or returned.

| Result | Response |
| --- | --- |
| First Google sign-in with an unused email | Creates a traveler and a Google identity, then returns `200` with `access_token`, `token_type: bearer`, and `expires_in`; sets the existing refresh cookie. |
| Returning linked Google identity | Resolves by stable `sub`, then returns the same session response. Changed Google email/name claims do not overwrite the local profile or select another account. |
| Email already belongs to an account not linked to this `sub` | `409`, with `detail.code: google_link_required` and a message to use the existing sign-in method. No identity is linked and no session is issued. |
| Invalid/expired token, invalid subject, or unverified email | `401`: `Invalid Google ID token or unverified email.` |
| Google sign-in unconfigured / Google unavailable | `503`; no account or session is created. |
| Malformed JSON fields / untrusted Origin | Existing `422` validation / `403` Origin protection. Submitted token values are omitted from validation errors. |

Google sign-in reuses the existing JWT, refresh rotation, cookie, `/auth/me`, and logout implementation. Replacing the current browser session revokes the prior session; logout revokes its access and refresh tokens. Other device sessions remain independent. There is no automatic account-linking endpoint in this increment.

Google-only travelers have an empty password hash, explicitly disabling email/password sign-in. Forgot-password still returns its generic `202`, but sends no email and creates no reset token for them. Reset completion also refuses Google-only accounts, even if a stray reset-token row exists. Re-registering that email cannot enable a password.

### Google Cloud Console configuration

In the team's Google Cloud project, configure the OAuth consent screen/Google Auth Platform branding and audience: application name, support/developer contact, authorized production domains, homepage/privacy URLs as applicable, and approved test users while the app is in Testing. Create an **OAuth client ID** with application type **Web application**.

Configure **Authorized JavaScript origins** for the exact future frontend origins (scheme, hostname, and port; no paths): `http://127.0.0.1:5173` for this repository's local Vite setup and the team's actual HTTPS production origin. If using localhost instead, register `http://localhost` and `http://localhost:5173`, and also update the backend Origin allowlist and local frontend host configuration consistently. Do not substitute the backend port for the frontend origin.

For the GIS popup/JavaScript callback followed by a JSON POST, no authorized redirect URI is required for this endpoint. Do not configure `/auth/google` as a direct Google form-post callback: that would require a separate integration and Google's CSRF-token handling. The same public web client ID is in `backend/.env.development` and `frontend/.env.development`; edit both files together in VS Code if the team changes it. This verification flow needs **no client secret, service-account key, or Google API access credentials**. Do not commit those credentials or token samples.

See Google's [GIS setup guide](https://developers.google.com/identity/gsi/web/guides/get-google-api-clientid) and [server-side ID-token verification guide](https://developers.google.com/identity/gsi/web/guides/verify-google-id-token).

### Local backend setup and testing

After the one-time setup above, start the backend from `backend/`:

```powershell
.\.venv\Scripts\python.exe dev.py run
```

The client ID is already tracked for local development. Google Cloud still needs `http://127.0.0.1:5173` as an authorized JavaScript origin, and test users must be allowed while the app is in Testing. If `GOOGLE_CLIENT_ID` is unset/empty in a production process, Google sign-in is disabled while other authentication remains available. A malformed configured client ID fails startup. Keep secure cookies enabled for HTTPS deployments.

Run focused tests with `.\.venv\Scripts\python.exe -m pytest tests/test_google_auth.py -q`, or the full regression suite with `.\.venv\Scripts\python.exe -m pytest -q`. Tests mock Google's verifier, block outbound requests, use temporary databases, and need no Google account/client ID, SMTP server, or real credentials. They verify application behavior and that the configured audience is passed to the supported verifier; they do not replace a live Google signature/integration check.

After the team configures its Console project, use the frontend Google button to send a freshly obtained ID token to `/auth/google`, then check `/auth/me`, refresh, and logout. Test a new Google traveler, a repeat sign-in, and a collision with a password account (expect `409`). Do not put ID tokens in URL queries, shell history, logs, or committed fixtures.

Existing local databases are preserved: local development startup creates missing tables, including `googleidentity`, without dropping/rebuilding the traveler table or changing existing password hashes. The original non-null password column remains compatible; only newly created Google-only accounts use the disabled empty value. Deployment uses the Alembic migration step above.

## Forgotten-password reset

| Endpoint | JSON input | Response |
| --- | --- | --- |
| `POST /auth/forgot-password` | `email` | `202`: `{"detail":"If an account exists for that email, a password reset email will be sent."}` |
| `POST /auth/reset-password` | `token`, `password` | `204`: password replaced; sign in again |

The request response is identical for known emails, unknown emails, rate-limited requests, and SMTP delivery failures. Invalid request shapes return `422` without submitted values. If reset email is not configured, all valid email requests return the same `503`. Both endpoints enforce the existing Origin allowlist and use `Cache-Control: no-store`.

Tokens use 32 cryptographically random bytes; only SHA-256 hashes are stored. A token expires 30 minutes after issuance. Reset completion consumes the token, hashes the new password with bcrypt cost 12, invalidates all outstanding reset links, and revokes every login session for that traveler in one transaction. The existing password rules apply: at least 8 characters, at most 72 UTF-8 bytes, with no trimming. Invalid, expired, and reused tokens all return `400` with `Invalid or expired password reset token.` Invalid passwords do not consume the link. A successful reset returns no access token, clears the refresh cookie, and requires fresh sign-in. Old access tokens and refresh cookies stop working on all devices.

Database write locks and a conditional token update ensure only one simultaneous reset succeeds, even when two different outstanding links are used. Login and token issuance also serialize with reset completion. Merely requesting an email does not change the password or revoke sessions.

Limits are shared in the database across workers/restarts and apply equally to known and unknown emails: one request per normalized email per 60 seconds, five per email per hour, and 20 per client IP per hour. These are windows starting at the first admitted request; repeated requests count against the hourly allowance even during the minute cooldown. Suppressed email requests retain the generic `202`. Reset completion allows 60 attempts per client IP per hour, then returns `429` with `Retry-After: 3600`. The application uses `request.client.host`, never parses forwarded headers itself. Configure Uvicorn's trusted proxy list correctly behind a reverse proxy; do not trust arbitrary forwarded client IPs. Add edge limits for invalid JSON and broader abuse controls before public deployment.

### SMTP and trusted frontend URL

SMTP settings come from process environment variables; the local launcher loads only its JWT secret and Google client ID from the development files. No SMTP dependency is needed beyond Python's standard library.

| Variable | Required/default | Meaning |
| --- | --- | --- |
| `RESET_FRONTEND_URL` | Required to enable reset email | Full trusted reset page URL, e.g. `https://travel.example.com/reset-password`; no credentials, query, or fragment. HTTPS required except loopback HTTP. |
| `SMTP_HOST` | Required to enable reset email | SMTP server hostname. |
| `SMTP_FROM` | Required when enabled | Valid sender email address, e.g. `no-reply@example.com`. |
| `SMTP_PORT` | `587` | Server port, 1–65535. Use the port required by your provider, usually 587 for STARTTLS or 465 for implicit TLS. |
| `SMTP_SECURITY` | `starttls` | `starttls`, `ssl` (implicit TLS), or `none`. Certificate verification is enabled for TLS. `none` is allowed only with loopback SMTP and no credentials. |
| `SMTP_USERNAME` | Empty | SMTP authentication username; omit for a local mail catcher. |
| `SMTP_PASSWORD` | Empty | SMTP authentication password; supply with username through your environment/secret manager. Never commit it. |
| `SMTP_TIMEOUT_SECONDS` | `10` | SMTP socket timeout, 1–60 seconds. |

If both `RESET_FRONTEND_URL` and `SMTP_HOST` are unset, reset email is disabled and existing authentication still runs. Partial or invalid configuration fails startup. The local launcher supplies the development JWT and cookie settings; supply production auth settings separately. Add your exact frontend origin to `AUTH_ALLOWED_ORIGINS` in deployment; the reset page URL setting does not change that allowlist.

Links are built only from `RESET_FRONTEND_URL`, never Host, Origin, or forwarded headers. The link format is `<RESET_FRONTEND_URL>#token=<random-token>`. Configure the frontend reset page path as `/reset-password`; the frontend reads the fragment, replaces it in browser history with `#set-new-password`, and POSTs the token and new password in JSON to `/auth/reset-password`. Tokens stay in memory, never localStorage or sessionStorage. Reloading after the fragment is removed requires reopening the original email link or requesting another. Fragments avoid putting the token in HTTP page requests and access logs. The frontend host must serve the SPA at `/reset-password` (Vite does this locally). Do not enable request-body logging, SMTP debug logging, SQL parameter logging, or message-body capture in production monitoring. The application never logs reset links, tokens, passwords, or provider exceptions.

SMTP delivery runs after the generic response via a FastAPI background task, with an injectable `ResetSender` interface (`create_app(..., reset_sender=fake)`). If delivery fails or is uncertain, the token is deleted and the response remains generic. This is best-effort delivery, not a durable queue: a process crash can lose a pending email. The user can retry after the cooldown. Expired rate-limit rows and expired reset tokens are cleaned during requests; schedule maintenance for unused/expired auth records at deployment scale.

### Local testing without an email account

Use [Mailpit's official Docker image](https://mailpit.axllent.org/docs/install/docker/) to capture email locally; it does not deliver to real inboxes. With Docker installed, run in a separate terminal:

```powershell
docker run --rm --name taasheera-mailpit -p 127.0.0.1:1025:1025 -p 127.0.0.1:8025:8025 axllent/mailpit
```

In the backend terminal, set these Mailpit settings before starting the local development launcher:

```powershell
$env:SMTP_HOST = "127.0.0.1"
$env:SMTP_PORT = "1025"
$env:SMTP_SECURITY = "none"
$env:SMTP_FROM = "no-reply@example.com"
$env:SMTP_USERNAME = ""
$env:SMTP_PASSWORD = ""
$env:SMTP_TIMEOUT_SECONDS = "10"
$env:RESET_FRONTEND_URL = "http://127.0.0.1:5173/reset-password"
.\.venv\Scripts\python.exe dev.py run
```

1. Register a test traveler through http://127.0.0.1:8000/docs and sign in. Save an access token temporarily to test revocation.
2. Call `/auth/forgot-password` with that email. Open http://127.0.0.1:8025 to view the captured email. Call the same endpoint with an unknown email: the API response must match, and no extra email should appear.
3. Start Vite with `npm.cmd run dev` from `frontend/`. Open the email link to reach **Set new password**, enter matching valid passwords, and submit. Alternatively, copy the value after `#token=` directly into the `/auth/reset-password` JSON body in Swagger. Do not put the token in a shell command or URL query. The complete Windows frontend/Mailpit checklist is in `frontend/README.md`.
4. Expect `204`. Reuse the link: expect `400`. Sign in with the old password: expect `401`; the new password: expect `200`. Test the previously saved access token against `/auth/me`: expect `401`.
5. Stop Mailpit, wait at least 60 seconds, and request another email. The generic `202` response remains unchanged and the failed-delivery token is invalidated. Restart Mailpit to resume email capture.

Automated tests use a fake sender and temporary databases, requiring neither Docker, SMTP credentials, nor a real email account. SMTP transport is tested with a fake connection, including STARTTLS and implicit TLS; concurrency tests use separate clients/threads. Run the full suite with `.\.venv\Scripts\python.exe -m pytest -q`.

SMTP implementation reference: [Python smtplib](https://docs.python.org/3/library/smtplib.html).

## Database configuration

Password reset adds `passwordresettoken` and `resetratelimit` tables without changing existing traveler columns. Local development creates missing tables at startup; deployment uses Alembic.

The local default is `backend/taasheera.db`, regardless of the working directory. Local development creates missing tables at startup. To change the database, set `DATABASE_URL` before starting the server:

```powershell
$env:DATABASE_URL = "sqlite:///./another-local.db"
.\.venv\Scripts\python.exe dev.py run
```

Relative SQLite paths are relative to the working directory. Production configuration comes from the process environment; the local development launcher reads only `backend/.env.development` and Git-ignored `backend/.env.local`. Other SQLAlchemy database URLs can be used later, but require the appropriate driver and database setup. Database files, virtual environments, local tools, local `.env` files, and common secret files are ignored by Git.

## Registration contract

Send JSON with `name`, `email`, and `password`:

```json
{"name": "Maya Haddad", "email": "maya@example.com", "password": "example-password-123"}
```

- `201`: returns only `id`, `name`, and normalized `email`.
- `409`: email already registered. A database unique constraint also protects against concurrent duplicates.
- `422`: invalid input. Validation responses omit submitted values so passwords are not echoed.

Names are trimmed and must contain 1–100 characters. Emails are validated, trimmed, and lowercased for case-insensitive account identity. Passwords require at least 8 characters and at most 72 UTF-8 bytes; they are never trimmed or silently truncated. Passwords are hashed with bcrypt, a fresh salt, and cost 12. Only the hash is persisted; it is excluded from the response. Extra fields such as `role` or `id` are rejected. Password confirmation belongs to the frontend and is not part of this API.

## Team decisions

- Choose the managed PostgreSQL service and private storage before deployment. The driver and initial Alembic revision are in the repository; `create_all` is for local development only.
- Agree on the password minimum and bcrypt cost for the target server. The 72-byte limit is a bcrypt constraint, including for non-ASCII passwords.
- Confirm case-insensitive email identity and the explicit duplicate-email response. Email ownership verification is not implemented in this increment.
- Before deployment, agree on token lifetimes, secret management, HTTPS origins, login rate limiting, and a cleanup job for expired sessions and their retained refresh hashes. The initial migration includes the auth tables without changing existing traveler columns.

Implementation references: [FastAPI database sessions](https://fastapi.tiangolo.com/tutorial/sql-databases/), [SQLModel testing](https://sqlmodel.tiangolo.com/tutorial/fastapi/tests/), and [bcrypt usage and limits](https://pypi.org/project/bcrypt/).
Token/cookie references: [PyJWT validation](https://pyjwt.readthedocs.io/en/stable/api.html) and [Starlette cookie options](https://www.starlette.io/responses/).
