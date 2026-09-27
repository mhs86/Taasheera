# Taasheera frontend

React + TypeScript + Vite. Registration and email/password sign-in are connected to the backend. Signed-in travelers see their name from protected `/auth/me` and can log out. Google sign-in and password reset are still unavailable.

## Run locally on Windows

Use two PowerShell terminals, each starting at the repository root. The backend virtual environment and frontend dependencies must already be installed (see `backend/README.md`; run `npm.cmd install` in `frontend/` if needed).

Terminal 1:

```powershell
cd backend
$env:JWT_SECRET = (& .\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))")
$env:AUTH_COOKIE_SECURE = "false" # Required for refresh cookies on local HTTP.
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Terminal 2:

```powershell
cd frontend
npm.cmd run dev
```

Open http://127.0.0.1:5173/#create-account. You can also follow Create an account from sign-in. If port 5173 is occupied, stop the old Vite server before starting this one. Restart Vite after changing its configuration.

The browser calls `/auth` on the frontend origin. Vite forwards these requests to http://127.0.0.1:8000. No backend CORS allowance is needed. A production host must also route `/auth` to the API and use HTTPS with secure cookies. Use `127.0.0.1` consistently locally so the origin matches the backend allowlist.

Access tokens stay in JavaScript memory, never localStorage or sessionStorage. Reload calls `/auth/refresh` with the HttpOnly cookie, then `/auth/me` with the returned bearer token. Web Locks serialize login, refresh, and logout across same-origin tabs; concurrent React mounts share one restoration request. Use a current browser with Web Locks support (HTTPS or loopback HTTP). Logout only shows the signed-out view after backend revocation succeeds; failures offer a retry. Other open tabs update their displayed profile on reload.

## Test sign-in in the browser

1. Start both servers above and open http://127.0.0.1:5173/. Register a test traveler, then follow **Sign in**.
2. Enter that email and a wrong password. Expect `Invalid email or password.`, a cleared password field, and no signed-in view. Network should show `/auth/login` returning `401` and no `/auth/me` request.
3. Enter the correct password. Expect `/auth/login` returning `200`, followed by `/auth/me` returning `200` with a bearer Authorization header. The welcome heading must show the name returned by `/auth/me`.
4. Reload. Expect `/auth/refresh` then `/auth/me`, and the same welcome heading. A fresh signed-out browser instead receives `401` from refresh and shows sign-in. Reload two tabs concurrently to check serialized rotation.
5. Open `/auth/me` directly on the frontend origin: expect `401` because a refresh cookie alone does not authorize protected access. In developer tools, confirm neither localStorage nor sessionStorage contains tokens; the refresh cookie is HttpOnly, SameSite Strict, path `/auth`, and lacks Secure only for local HTTP.
6. Click **Log out**. Expect `/auth/logout` returning `204` and sign-in appearing. Reload and confirm you remain signed out. Reusing the prior bearer token against `/auth/me` must return `401` (also covered by backend tests).
7. While signed in, switch the browser offline and click **Log out**. Expect a visible error rather than a false success. Restore connectivity and retry; logout should succeed.

Automated session-module tests cover correct/wrong passwords, protected profile requests, restoration deduplication, missing cookies, profile failures, logout, and retryable failures. They mock HTTP; the backend suite separately exercises real API/session behavior. Browser visual and cookie checks require the manual steps above when no browser connection is available.

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
npm.cmd test # Node 22.18+ (native TypeScript stripping), validated with Node 24
```

From `backend/`:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```
