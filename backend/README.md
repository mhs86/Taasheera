# Taasheera backend — traveler authentication

The backend supports traveler registration, email/password and Google sign-in, a protected traveler profile, refresh, logout, password reset, and authenticated passport upload and extraction. The account page does not yet edit the new profile fields. Sign-up always creates an active traveler; an operator gives an existing account the admin role with `manage.py set-role` (see Roles and admin access).

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

`dev.py setup` creates `backend/.env.local` once with a private JWT signing secret; it never prints or replaces that secret. To use the passport assistant locally, add a line `GEMINI_API_KEY=<key>` to that same file (get a free key at https://aistudio.google.com, or ask the team for the shared test key privately). Never put the key in a tracked file: this repository is public. `dev.py run` automatically reads it and the public `GOOGLE_CLIENT_ID` in the tracked `backend/.env.development`, applies database migrations, then starts Uvicorn on `http://127.0.0.1:8000` with local HTTP cookies. No virtual environment activation or PowerShell execution-policy change is needed. If `py` is unavailable, use the full path to your installed Python for the first command.

`dev.py run` runs Alembic migrations before starting the server. Back up existing
local databases before the first run after a schema update. The SSO migration adds
nullable `traveler.sso_email`, preserves contact emails/password hashes, and
backfills the original verified email for existing Google identities. Later Google
sign-ins update this field from verified claims; it is never a login key. The newer
profile migration adds a separate `travelerprofile` table without changing `traveler`.

The local secret stays stable across restarts and is Git-ignored. The development launcher loads only these local settings; production startup still reads environment variables and must receive its own `JWT_SECRET`, `GOOGLE_CLIENT_ID`, and secure-cookie settings from deployment configuration. Never commit a production secret or Google Client Secret. Changing the JWT secret invalidates existing access JWTs; persisted refresh sessions still work until revoked or expired.

Open http://127.0.0.1:8000/docs to try registration. Stop the server with Ctrl+C. For a run-only environment, install `requirements.lock` instead of `requirements-dev.lock`.

Run the tests from `backend/` (CI installs `requirements-dev.lock`):

```powershell
$env:TEMP = "$env:USERPROFILE\pytest-tmp"
$env:TMP = "$env:USERPROFILE\pytest-tmp"
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider
```

Tests use isolated temporary SQLite databases and never the development database.
They generate their own signing secrets and require no developer secrets.

## Migration and container checks

Local `dev.py run` runs `python migrate.py upgrade` and then starts the API with
`SCHEMA_AUTO_CREATE=false`, like a deployment; only the tests build schemas with `create_all`.
A deployed process defaults to `SCHEMA_AUTO_CREATE=false` and refuses to start until the
Alembic schema revision is current. Before starting a new image, run `python migrate.py upgrade`
against its `DATABASE_URL`; `python migrate.py status` reports the current and required revisions.
The upgrade command creates a fresh schema. An unversioned database is stamped at the current
revision only when its schema exactly matches the current models, including CHECK constraints and
server defaults; one that matches a known earlier `create_all` schema is stamped at that revision
and then upgraded. Anything else is refused, and traveler data is never discarded. On SQLite the
role revision rebuilds the traveler table and copies all of its rows; an interrupted upgrade rolls
back completely. Back up a deployed database before its first migration. `dev.py run`
migrates the local database automatically, so copy `backend/taasheera.db` first if you want a
backup. Do not run migrations independently in every API replica.

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

## Traveler profile API

`GET /profile` and `PUT /profile` require the same bearer access token as `/auth/me`.
The profile is a separate row owned by the authenticated traveler; the request cannot choose
another traveler ID. Before a row exists, GET returns all fields as `null`. PUT replaces the
whole row, so omitted fields become `null`; an empty `given_names` or optional address line
is allowed. The account display name in `traveler.name` is separate.

The fields are `surname`, `given_names`, `birth_date`, `nationality`, `phone`,
`address_line1`, `address_line2`, `address_city`, `address_region`,
`address_postal_code`, and `address_country`. Dates use `YYYY-MM-DD` and must be in
the past. Country codes are 1–3 uppercase letters as printed on the passport
(for example `LBN` or `D`); the backend does not check country membership. Phones
must include an international `+` prefix and are validated and stored as E.164
using `phonenumbers`. Unknown fields are rejected. Responses disable caching,
and phone, address, and birth date are omitted from request logs.

To apply this migration manually to the local database from `backend/`, stop the
backend, run `.\.venv\Scripts\python.exe migrate.py upgrade`, then run
`.\.venv\Scripts\python.exe dev.py run`. The launcher also migrates automatically.

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
logout, passport upload/extraction outcomes, and role changes made with `manage.py set-role`
(`role_change`, identifier `cli:<old>-><new>`). `POST /activity/events` accepts only a bearer token,
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
revision includes this table; `dev.py run` applies the same migrations.

Anonymous clicks, duplicate-email registration attempts, unknown-email sign-in failures, invalid
Google credentials, and failed Google account collisions have no verified traveler owner, so they are
not stored. Refused `/admin` requests are not stored either; the request log keeps their route and
`403`. Browser activity requests are best effort; failed delivery is not queued for later retry.

## Login and session API

| Endpoint | Input | Success |
| --- | --- | --- |
| `POST /auth/login` | JSON `email`, `password` | `200`: `access_token`, `token_type: bearer`, `expires_in`; sets refresh cookie |
| `GET /auth/me` | `Authorization: Bearer <access_token>` | `200`: `id`, `name`, `email` |
| `POST /auth/refresh` | Refresh cookie, no JSON body or access token required | `200`: new access token and rotated refresh cookie |
| `POST /auth/logout` | Refresh cookie, no JSON body required | `204`: session revoked and cookie cleared; safe to repeat |
| `POST /auth/change-password` | Bearer access token; JSON `current_password`, `new_password` | `204`: password changed; other sessions revoked, current session retained |
| `GET /sessions` | Bearer access token | `200`: unexpired, unrevoked sessions owned by the traveler, with current session marked |
| `DELETE /sessions/{session_id}` | Bearer access token; allowed Origin | `204`: other owned session revoked; `400` for current session, `404` for unknown or another traveler's session |
| `POST /sessions/revoke-others` | Bearer access token; allowed Origin | `200`: `ended` count; current session remains valid |

Unknown emails and incorrect passwords return the same `401` message, `Invalid email or password.` Unknown emails still undergo bcrypt verification against a dummy hash. Request validation errors remain `422` and omit submitted values. Access tokens use HS256 with a fixed algorithm allowlist, issuer/audience checks, and required identity, session, issue-time and expiry claims. JWTs last at most 15 minutes. `/auth/me` accepts only a bearer access token, never just a cookie.

Refresh tokens contain 32 random bytes and are stored only as SHA-256 hashes. Their host-only `taasheera_refresh` cookie has `HttpOnly`, `SameSite=Strict`, and `Path=/auth`. `Secure` defaults to true; set `AUTH_COOKIE_SECURE=false` only for local HTTP. Responses containing tokens or profile data use `Cache-Control: no-store`.

A session expires seven days after login; rotation does not extend that deadline. Each refresh atomically replaces the current token. Reusing an older token revokes the entire session, including the replacement and all of its access tokens. Clients must serialize refresh requests, including across tabs: concurrent use of one cookie triggers this replay protection. Logout also immediately invalidates that session's access tokens through a database session check. Other independent device sessions remain valid. Re-login with an existing refresh cookie revokes the replaced browser session.

At login, the server derives a short browser/operating-system label from User-Agent without saving the raw header or IP, and stores UTC creation and last-active times. Last-active changes on successful refresh, not every request. Sessions created before this schema change retain null timestamps and appear as "Unknown device" when no label exists. Session-list responses never contain refresh-token hashes and use `Cache-Control: private, no-store`. Revocation takes effect on the next bearer request as well as the next refresh.

Signed-in email/password travelers can change their password without signing out their current
session. `POST /auth/change-password` requires the current password, a different new password
of 8 characters to 72 UTF-8 bytes, a bearer token, and an allowed Origin. It rejects extra fields,
Google-only accounts, and incorrect current passwords; attempts are rate-limited. On success,
the current access and refresh tokens remain valid, while all other sessions for that traveler
are revoked. The response contains no password or hash.

Cookie-changing endpoints check an incoming `Origin` against `AUTH_ALLOWED_ORIGINS`, a comma-separated exact allowlist. Defaults are `http://127.0.0.1:5173,http://127.0.0.1:8000`. Requests without an Origin are accepted for API clients unless marked cross-site by `Sec-Fetch-Site`. Configure exact HTTPS origins for deployment. This is CSRF protection, not a CORS allowance; no CORS middleware was added. The Vite development proxy forwards `/auth` to the backend on the same browser origin.

For a manual backend check, open http://127.0.0.1:8000/docs after starting with the environment above. Register a traveler, call login, copy only the returned access token into **Authorize**, then call `/auth/me`. Swagger/browser keeps the refresh cookie for refresh and logout. After logout, the old access token must return `401`. See `frontend/README.md` for the browser sign-in checklist.

## Roles and admin access

Every account has a `role` (`traveler`, `support` or `admin`) and a `status` (`active` or
`suspended`), stored on the traveler row. New accounts, and accounts that existed before roles,
are active travelers. Named database CHECK constraints reject any other value, including
different capitalization.

| Endpoint | Input | Success |
| --- | --- | --- |
| `GET /admin/me` | `Authorization: Bearer <access_token>` of an active admin | `200`: `id`, `name`, `email`, `role` |

Without a valid access token, `/admin` routes return `401` like `/auth/me`. Every other account,
including support staff and suspended admins, gets the same `403` with `Admin access required.`
Every response under `/admin`, including `401`, `403`, `404`, `405` and redirects, uses
`Cache-Control: no-store`, also behind a path prefix.
Access tokens carry no role: the role and status
are read from the database on every request, so a change applies to the next request. Suspension
only affects `/admin` until US 133 adds sign-in enforcement.

No sign-up path accepts a role. To create the first admin, the person signs up normally; confirm
with them that they control that account (password-account emails are not verified, so prefer a
Google account). Then run from `backend/`:

```powershell
.\.venv\Scripts\python.exe manage.py set-role --email <email> --role admin
```

The command changes only the role of an existing account, never handles passwords, and records a
`role_change` activity event in the same transaction. It prints the account ID and sign-in method,
never the email, and refuses a SQLite path that does not exist instead of creating an empty
database. The same command sets `traveler` or `support`. On the AWS host (through Systems
Manager), run it in the API service, which already has the production settings and storage volume:
`docker compose -f /opt/taasheera/deploy/aws/compose.yaml run --rm api python manage.py set-role --email <email> --role admin`.
Elsewhere, run it as a one-off task from the backend image (which contains `manage.py`) with that
environment's `DATABASE_URL`, and mount the API's storage volume so the JSONL mirror joins its
activity logs; without the mount only the database event is kept. The Lambda image does not
include `manage.py`, and the free Render database refuses outside connections.

## Google sign-in

`POST /auth/google` accepts JSON `{"id_token":"<Google Identity Services credential>"}`. The frontend sends the **ID token** from the GIS JavaScript callback, not a Google API access token or authorization code. The endpoint is a same-origin JSON API, not Google's direct HTML form/redirect callback.

The backend uses `google.oauth2.id_token.verify_oauth2_token` from the supported `google-auth` library to verify the signature, configured audience, issuer, and expiry. It additionally requires `email_verified: true`, a valid email, and a nonempty string `sub`. Google certificates are fetched over HTTPS with a 10-second request timeout; provider transport failures return `503`. Tokens and verifier exception details are not logged or returned.

| Result | Response |
| --- | --- |
| First Google sign-in with an unused email | Creates a traveler and a Google identity, then returns `200` with `access_token`, `token_type: bearer`, and `expires_in`; sets the existing refresh cookie. |
| Returning linked Google identity | Resolves by stable `sub`, then returns the same session response. Verified provider email updates `sso_email`; the contact email/name and account identity stay unchanged. |
| Email already belongs to an account not linked to this `sub` | `409`, with `detail.code: google_link_required` and a message to use the existing sign-in method. No identity is linked and no session is issued. |
| Invalid/expired token, invalid subject, or unverified email | `401`: `Invalid Google ID token or unverified email.` |
| Google sign-in unconfigured / Google unavailable | `503`; no account or session is created. |
| Malformed JSON fields / untrusted Origin | Existing `422` validation / `403` Origin protection. Submitted token values are omitted from validation errors. |

Google sign-in reuses the existing JWT, refresh rotation, cookie, `/auth/me`, and logout implementation. Replacing the current browser session revokes the prior session; logout revokes its access and refresh tokens. Other device sessions remain independent. Account linking is explicit, never automatic by matching email.

`GET /auth/config` publicly returns only `google_client_id`, with `Cache-Control:
no-store`. The frontend uses this AWS/backend setting instead of a separately
compiled client ID. JWT signing secrets, client secrets, and provider keys are
never included.

`POST /auth/google/link` requires a valid bearer session, an allowed origin,
the current application password, a Google ID token, and `expected_traveler_id`
matching the authenticated owner. The last field guards against another browser
tab changing the cookie account during session refresh; it does not select the
link target. The verified Google subject may belong to only one traveler, and
an existing different Google identity cannot be replaced. Repeated linking of
the same identity is safe. The response is the owner's public profile, including
`sso_email`; contact email and password remain unchanged. The server records only
an owner-scoped `account_link` audit event, excluding token, password and email.

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

Existing local databases are preserved: `dev.py run` applies required schema updates with Alembic without changing existing password hashes or traveler IDs. The original non-null password column remains compatible; only newly created Google-only accounts use the disabled empty value. Deployment uses the Alembic migration step above.

## Forgotten-password reset

Password-enabled accounts recover using an emailed six-digit code, verified by
`POST /auth/verify-reset-code` before setting a new password. Google-only accounts
recover through Google and cannot obtain a local password through this API.
See [OTP API, security controls, admin reporting and AWS setup](../docs/AUTH_OTP_AWS.md).

Local SMTP remains available for a private Mailpit catcher: set `SMTP_HOST=127.0.0.1`,
`SMTP_PORT=1025`, `SMTP_SECURITY=none`, `SMTP_FROM=specimen@example.com`, and
`RESET_FRONTEND_URL=http://127.0.0.1:5173/reset-password` before `python dev.py run`.
The URL is retained for compatible SMTP configuration validation; messages contain
codes, not links. Production uses SES with the EC2 role and no SMTP credentials.
A failed/uncertain send invalidates its challenge. Delivery is a background task,
not a durable queue; after a process crash the user may need to request a new code.
Never enable message-body, SQL-parameter, or SMTP debug logging in production.

## Database configuration

Password reset uses `passwordresetchallenge`, `passwordresettoken`, and `resetratelimit`. Alembic also adds account-type fields, the role and status fields, and the private `admin_user_auth` view.

The local default is `backend/taasheera.db`, regardless of the working directory. Local development applies Alembic migrations before startup. To change the database, set `DATABASE_URL` before starting the server:

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

Names are trimmed and must contain 1–100 characters. Emails are validated, trimmed, and lowercased for case-insensitive account identity. Passwords require at least 8 characters and at most 72 UTF-8 bytes; they are never trimmed or silently truncated. Passwords are hashed with bcrypt, a fresh salt, and cost 12. Only the hash is persisted; it is excluded from the response. Extra fields such as `role` or `id` are rejected. New accounts are always active travelers. Password confirmation belongs to the frontend and is not part of this API.

## Team decisions

- Choose the managed PostgreSQL service and private storage before deployment. The driver and Alembic revisions are in the repository; `create_all` is for tests only.
- Agree on the password minimum and bcrypt cost for the target server. The 72-byte limit is a bcrypt constraint, including for non-ASCII passwords.
- Confirm case-insensitive email identity and the explicit duplicate-email response. Email ownership verification is not implemented in this increment.
- Before deployment, agree on token lifetimes, secret management, HTTPS origins, login rate limiting, and a cleanup job for expired sessions and their retained refresh hashes. The initial migration includes the auth tables without changing existing traveler columns.

Implementation references: [FastAPI database sessions](https://fastapi.tiangolo.com/tutorial/sql-databases/), [SQLModel testing](https://sqlmodel.tiangolo.com/tutorial/fastapi/tests/), and [bcrypt usage and limits](https://pypi.org/project/bcrypt/).
Token/cookie references: [PyJWT validation](https://pyjwt.readthedocs.io/en/stable/api.html) and [Starlette cookie options](https://www.starlette.io/responses/).

Google SSO, email OTP reset, account types, administrator reporting and AWS SES rollout:
[Authentication operations](../docs/AUTH_OTP_AWS.md). Recovery now verifies a six-digit
code before issuing a short-lived password-reset grant; prior email links are invalidated.
