# Taasheera backend — traveler authentication

The backend supports traveler registration, email/password login, a protected profile, refresh, logout, and email-based password reset. The frontend connects registration, sign-in, and password reset, displays the protected traveler profile, restores sessions after reload, and supports logout. There is no admin registration or Google sign-in.

## Windows setup and run

Install Python 3.12 or newer. From the repository root in PowerShell:

```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
$env:JWT_SECRET = (& .\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))")
$env:AUTH_COOKIE_SECURE = "false" # Local HTTP only; keep true for HTTPS deployments.
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

No virtual environment activation or PowerShell execution-policy change is needed. If `py` is unavailable, use the full path to your installed Python for the first command.

The secret command assigns a generated value without printing it to the terminal. Keep the same secret across processes/restarts that should accept existing access tokens. Supply a persistent secret through your deployment's environment/secret manager; never commit it. `.env` files are ignored but are not automatically loaded. Startup fails if `JWT_SECRET` is missing or shorter than 32 bytes. Changing it invalidates existing access JWTs; persisted refresh sessions still work until revoked or expired.

Open http://127.0.0.1:8000/docs to try registration. Stop the server with Ctrl+C. For a run-only environment, install `requirements.txt` instead of `requirements-dev.txt`.

Run the tests from `backend/`:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Tests use isolated temporary SQLite databases and never the development database.
They generate their own signing secrets and require no developer secrets.

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

All settings come from process environment variables; `.env` files are not loaded automatically. No SMTP dependency is needed beyond Python's standard library.

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

If both `RESET_FRONTEND_URL` and `SMTP_HOST` are unset, reset email is disabled and existing authentication still runs. Partial or invalid configuration fails startup. Supply the existing `JWT_SECRET`, `AUTH_COOKIE_SECURE`, and `AUTH_ALLOWED_ORIGINS` settings as described above as well. Add your exact frontend origin to `AUTH_ALLOWED_ORIGINS` in deployment; the reset page URL setting does not change that allowlist.

Links are built only from `RESET_FRONTEND_URL`, never Host, Origin, or forwarded headers. The link format is `<RESET_FRONTEND_URL>#token=<random-token>`. Configure the frontend reset page path as `/reset-password`; the frontend reads the fragment, replaces it in browser history with `#set-new-password`, and POSTs the token and new password in JSON to `/auth/reset-password`. Tokens stay in memory, never localStorage or sessionStorage. Reloading after the fragment is removed requires reopening the original email link or requesting another. Fragments avoid putting the token in HTTP page requests and access logs. The frontend host must serve the SPA at `/reset-password` (Vite does this locally). Do not enable request-body logging, SMTP debug logging, SQL parameter logging, or message-body capture in production monitoring. The application never logs reset links, tokens, passwords, or provider exceptions.

SMTP delivery runs after the generic response via a FastAPI background task, with an injectable `ResetSender` interface (`create_app(..., reset_sender=fake)`). If delivery fails or is uncertain, the token is deleted and the response remains generic. This is best-effort delivery, not a durable queue: a process crash can lose a pending email. The user can retry after the cooldown. Expired rate-limit rows and expired reset tokens are cleaned during requests; schedule maintenance for unused/expired auth records at deployment scale.

### Local testing without an email account

Use [Mailpit's official Docker image](https://mailpit.axllent.org/docs/install/docker/) to capture email locally; it does not deliver to real inboxes. With Docker installed, run in a separate terminal:

```powershell
docker run --rm --name taasheera-mailpit -p 127.0.0.1:1025:1025 -p 127.0.0.1:8025:8025 axllent/mailpit
```

In the backend terminal, set these before starting Uvicorn (alongside the existing JWT/local-cookie settings):

```powershell
$env:SMTP_HOST = "127.0.0.1"
$env:SMTP_PORT = "1025"
$env:SMTP_SECURITY = "none"
$env:SMTP_FROM = "no-reply@example.com"
$env:SMTP_USERNAME = ""
$env:SMTP_PASSWORD = ""
$env:SMTP_TIMEOUT_SECONDS = "10"
$env:RESET_FRONTEND_URL = "http://127.0.0.1:5173/reset-password"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

1. Register a test traveler through http://127.0.0.1:8000/docs and sign in. Save an access token temporarily to test revocation.
2. Call `/auth/forgot-password` with that email. Open http://127.0.0.1:8025 to view the captured email. Call the same endpoint with an unknown email: the API response must match, and no extra email should appear.
3. Start Vite with `npm.cmd run dev` from `frontend/`. Open the email link to reach **Set new password**, enter matching valid passwords, and submit. Alternatively, copy the value after `#token=` directly into the `/auth/reset-password` JSON body in Swagger. Do not put the token in a shell command or URL query. The complete Windows frontend/Mailpit checklist is in `frontend/README.md`.
4. Expect `204`. Reuse the link: expect `400`. Sign in with the old password: expect `401`; the new password: expect `200`. Test the previously saved access token against `/auth/me`: expect `401`.
5. Stop Mailpit, wait at least 60 seconds, and request another email. The generic `202` response remains unchanged and the failed-delivery token is invalidated. Restart Mailpit to resume email capture.

Automated tests use a fake sender and temporary databases, requiring neither Docker, SMTP credentials, nor a real email account. SMTP transport is tested with a fake connection, including STARTTLS and implicit TLS; concurrency tests use separate clients/threads. Run the full suite with `.\.venv\Scripts\python.exe -m pytest -q`.

SMTP implementation reference: [Python smtplib](https://docs.python.org/3/library/smtplib.html).

## Database configuration

Password reset adds `passwordresettoken` and `resetratelimit` tables, created at startup; it does not change existing traveler columns. Use migrations before applying future changes to existing shared tables.

The default is `backend/taasheera.db`, regardless of the working directory. Tables are created at startup. To change the database, set `DATABASE_URL` before starting the server:

```powershell
$env:DATABASE_URL = "sqlite:///./another-local.db"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Relative SQLite paths are relative to the working directory. Configuration comes from the process environment; `.env` files are not automatically loaded. Other SQLAlchemy database URLs can be used later, but require the appropriate driver and database setup. Database files, virtual environments, local tools, `.env` files, and common secret files are ignored by Git.

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

- Choose the shared database and driver, and adopt migrations before evolving a shared schema. `create_all` creates missing tables; it does not migrate existing ones.
- Agree on the password minimum and bcrypt cost for the target server. The 72-byte limit is a bcrypt constraint, including for non-ASCII passwords.
- Confirm case-insensitive email identity and the explicit duplicate-email response. Email ownership verification is not implemented in this increment.
- Before deployment, agree on token lifetimes, secret management, HTTPS origins, login rate limiting, and a cleanup job for expired sessions and their retained refresh hashes. New auth tables are created on startup; no existing traveler columns change.

Implementation references: [FastAPI database sessions](https://fastapi.tiangolo.com/tutorial/sql-databases/), [SQLModel testing](https://sqlmodel.tiangolo.com/tutorial/fastapi/tests/), and [bcrypt usage and limits](https://pypi.org/project/bcrypt/).
Token/cookie references: [PyJWT validation](https://pyjwt.readthedocs.io/en/stable/api.html) and [Starlette cookie options](https://www.starlette.io/responses/).
