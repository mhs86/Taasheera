# Taasheera frontend

React + TypeScript + Vite. Create account is connected to the registration API. Sign-in, Google sign-in, and password reset are still unavailable.

## Run locally on Windows

Use two PowerShell terminals, each starting at the repository root. The backend virtual environment and frontend dependencies must already be installed (see `backend/README.md`; run `npm.cmd install` in `frontend/` if needed).

Terminal 1:

```powershell
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Terminal 2:

```powershell
cd frontend
npm.cmd run dev
```

Open http://127.0.0.1:5173/#create-account. You can also follow Create an account from sign-in. If port 5173 is occupied, stop the old Vite server before starting this one. Restart Vite after changing its configuration.

The browser posts JSON containing only `name`, `email`, and `password` to `/auth/register` on the frontend origin. Vite forwards that exact path to http://127.0.0.1:8000. Confirmation stays in the form. No backend CORS allowance is needed. This is a development proxy; a production host must route `/auth/register` to the API too. See [Vite proxy documentation](https://vite.dev/config/server-options.html#server-proxy).

## Test registration in the browser

1. Enter a name, a new email such as `traveler-test-1@example.com`, and matching passwords of at least 8 characters, such as `Travel-test-123`. Submit. Expect an account-created message, cleared fields, and no automatic sign-in. This creates a real traveler in the configured development database.
2. Submit again using the same email and valid passwords. Expect an already-registered message. Email matching is case-insensitive. Password fields clear after each request, including errors.
3. Leave a required field empty, enter an invalid email, or enter mismatching passwords. The browser should block submission. To exercise an API validation response, use matching passwords of 73 ASCII characters: expect the password length message and no account creation. The limit is 72 UTF-8 bytes, so non-ASCII passwords may reach it sooner.
4. In browser developer tools, select a slow network preset, then submit with a new email. The button should say Creating account and stay disabled while the request runs. The fields are disabled too; repeated clicks should not create extra requests. Return network throttling to normal afterwards.
5. Stop FastAPI with Ctrl+C, keep Vite running, and submit a valid form. Expect a backend-unavailable message. For a browser network failure, select Offline in developer tools after loading the page, then submit. Expect a connection message. Restore the connection and restart FastAPI afterwards.

Requests time out after 15 seconds. A connection failure can occur after the server creates an account; the message explains that retrying may therefore report a duplicate email. Passwords are not written to storage or logs. The API returns public user details without a password hash.

## Checks

From `frontend/`:

```powershell
npm.cmd run build
npm.cmd run lint
```

From `backend/`:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```
