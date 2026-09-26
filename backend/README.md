# Taasheera backend — traveler registration

This first backend piece provides only `POST /auth/register`. The frontend Create account form calls this endpoint through Vite's local proxy; see [browser testing instructions](../frontend/README.md). There is no admin registration, login, JWT, Google sign-in, or password reset.

## Windows setup and run

Install Python 3.12 or newer. From the repository root in PowerShell:

```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

No virtual environment activation or PowerShell execution-policy change is needed. If `py` is unavailable, use the full path to your installed Python for the first command.

Open http://127.0.0.1:8000/docs to try registration. Stop the server with Ctrl+C. For a run-only environment, install `requirements.txt` instead of `requirements-dev.txt`.

Run the tests from `backend/`:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Tests use isolated temporary SQLite databases and never the development database.

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

Implementation references: [FastAPI database sessions](https://fastapi.tiangolo.com/tutorial/sql-databases/), [SQLModel testing](https://sqlmodel.tiangolo.com/tutorial/fastapi/tests/), and [bcrypt usage and limits](https://pypi.org/project/bcrypt/).
