# Taasheera frontend

React + TypeScript + Vite. Registration, email/password sign-in, and password reset are connected to the backend. Signed-in travelers see their name from protected `/auth/me` and can log out. Google sign-in is still unavailable.

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

## Test password reset with Mailpit on Windows

These are manual instructions; Mailpit is not installed or started by the frontend tests. With Docker already available, use three PowerShell terminals. The backend virtual environment and frontend npm dependencies must already be installed.

Terminal 1, local email capture (this command downloads the Mailpit image if absent; run it only when ready to set up Mailpit):

```powershell
docker run --rm --name taasheera-mailpit -p 127.0.0.1:1025:1025 -p 127.0.0.1:8025:8025 axllent/mailpit
```

Terminal 2, from the repository root (stop any earlier backend server first):

```powershell
cd backend
$env:JWT_SECRET = (& .\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))")
$env:AUTH_COOKIE_SECURE = "false"
$env:AUTH_ALLOWED_ORIGINS = "http://127.0.0.1:5173,http://127.0.0.1:8000"
$env:SMTP_HOST = "127.0.0.1"
$env:SMTP_PORT = "1025"
$env:SMTP_SECURITY = "none"
$env:SMTP_FROM = "no-reply@example.com"
$env:SMTP_USERNAME = ""
$env:SMTP_PASSWORD = ""
$env:SMTP_TIMEOUT_SECONDS = "10"
$env:RESET_FRONTEND_URL = "http://127.0.0.1:5173/reset-password"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Terminal 3, from the repository root:

```powershell
cd frontend
npm.cmd run dev
```

1. Open http://127.0.0.1:5173/#create-account. Register a new traveler with a unique test email and password; then follow **Sign in → Forgot your password?**.
2. Enter that email and submit. While sending, the input and button are disabled; repeated clicks must produce only one POST to `/auth/forgot-password`. Expect exactly: `If an account exists for that email, a password reset email will be sent.` Repeat with an unknown email: the confirmation must be identical.
3. Open http://127.0.0.1:8025. Only the registered email should have a captured message. Open its link: its format is `http://127.0.0.1:5173/reset-password#token=...`. Expect **Set new password** and the address bar to change to `/reset-password#set-new-password` without the token. No token should appear in localStorage/sessionStorage or console logs. The link works even when the browser already has a signed-in session.
4. Enter mismatching passwords, then a too-short password, then 37 `é` characters (74 UTF-8 bytes). Each must block submission. Enter matching valid passwords and submit. Expect one POST to `/auth/reset-password` containing only `token` and `password`; the button stays disabled during the request.
5. Expect `204`, cleared password inputs, a success message, and a **Sign in** link. Follow it. The old password must fail; the new password must succeed. Reload the signed-in view and test **Log out** to confirm the existing session flow still works. Any session from before reset must fail protected access/refresh.
6. Reopen the original email link and submit valid passwords: expect the invalid/expired/already-used message and **Request a new reset link**. Open http://127.0.0.1:5173/reset-password without a token: expect a missing-link message and the same recovery link. Reload a freshly opened reset page after the token has been scrubbed: expect this missing-link state; reopen the email to continue.
7. To test expiration, request a fresh link after the 60-second cooldown, leave it unused for over 30 minutes, then open it and submit valid passwords. Expect the expired-link message. Expired/reused status is checked on submission; there is no separate token-validation endpoint.
8. For network errors, load each form first, switch developer tools to **Offline**, then submit. Expect a clear connection error, re-enabled controls, and cleared password fields on the reset form. Restore connectivity and retry. A timeout can happen after a reset succeeded; the message explains signing in with the new password or requesting another link.
9. For server errors, stop FastAPI and submit from either loaded form. Expect an unavailable/error message rather than success. Restart FastAPI. For SMTP failure, stop Mailpit and request a link after the cooldown: the generic confirmation remains unchanged by design, no email arrives, and the backend invalidates the failed-delivery token.

The backend suppresses repeated email requests (one per email per minute, five per email per hour, 20 per client IP per hour) without changing the generic confirmation. Reset submission returns `429` after 60 attempts per IP per hour; the form shows a wait message and allows later retry. Do not hammer the local service to test this manually; automated tests cover that UI state.

Use the exact configured reset URL above locally. Production hosting must serve the SPA at `/reset-password` and proxy `/auth` to FastAPI. Do not configure a fragment or query in `RESET_FRONTEND_URL`: the backend adds `#token=...`. The token is held only in memory; navigation away, success, or an invalid-link response clears the active reset flow. Password reset never signs the traveler in automatically.

Frontend tests exercise the real React forms under StrictMode in jsdom with mocked HTTP: generic confirmation, duplicate submission, missing/malformed/expired/reused links, history cleanup, validation, success, server/network errors, retries, signed-in reset access, and existing registration/sign-in navigation. SMTP delivery and database behavior are covered by the full backend suite. These tests do not replace a real-browser Mailpit check.

## Checks

From `frontend/`:

```powershell
npm.cmd run build
npm.cmd run lint
npm.cmd test # Node 22.22.2+ or 24.15+; validated with Node 24.21
```

From `backend/`:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```
