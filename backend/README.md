# Taasheera backend — traveler authentication

The backend supports traveler registration, email/password login, a protected profile, refresh, and logout. The frontend connects registration and sign-in, displays the protected traveler profile, restores sessions after reload, and supports logout. There is no admin registration, Google sign-in, or password reset.

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

## Database configuration

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
