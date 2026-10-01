# Taasheera frontend

React + TypeScript + Vite. Registration, email/password sign-in, Google sign-in, and password reset are connected to the backend. Signed-in travelers see their name from protected `/auth/me` and can log out. Google sign-in requires the public client ID configured below; email/password sign-in works without it.

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

Open http://127.0.0.1:5173/sign-in#create-account. You can also follow Get started from the homepage. If port 5173 is occupied, stop the old Vite server before starting this one. Restart Vite after changing its configuration.

The browser calls `/auth` and `/passports` on the frontend origin. Vite forwards these requests to http://127.0.0.1:8000. No backend CORS allowance is needed. A production host must route both prefixes to the API and use HTTPS with secure cookies. Use `127.0.0.1` consistently locally so the origin matches the backend allowlist.

Access tokens stay in JavaScript memory, never localStorage or sessionStorage. Reload calls `/auth/refresh` with the HttpOnly cookie, then `/auth/me` with the returned bearer token. Web Locks serialize login, refresh, and logout across same-origin tabs; concurrent React mounts share one restoration request. Use a current browser with Web Locks support (HTTPS or loopback HTTP). Logout only shows the signed-out view after backend revocation succeeds; failures offer a retry. Other open tabs update their displayed profile on reload.

## Test sign-in in the browser

1. Start both servers above and open http://127.0.0.1:5173/. Follow **Get started**, register a test traveler, then follow **Sign in**.
2. Enter that email and a wrong password. Expect `Invalid email or password.`, a cleared password field, and no signed-in view. Network should show `/auth/login` returning `401` and no `/auth/me` request.
3. Enter the correct password. Expect `/auth/login` returning `200`, followed by `/auth/me` returning `200` with a bearer Authorization header. The welcome heading must show the name returned by `/auth/me`.
4. Reload. Expect `/auth/refresh` then `/auth/me`, and the same welcome heading. A fresh signed-out browser instead receives `401` from refresh and shows sign-in. Reload two tabs concurrently to check serialized rotation.
5. Open `/auth/me` directly on the frontend origin: expect `401` because a refresh cookie alone does not authorize protected access. In developer tools, confirm neither localStorage nor sessionStorage contains tokens; the refresh cookie is HttpOnly, SameSite Strict, path `/auth`, and lacks Secure only for local HTTP.
6. Click **Log out**. Expect `/auth/logout` returning `204` and sign-in appearing. Reload and confirm you remain signed out. Reusing the prior bearer token against `/auth/me` must return `401` (also covered by backend tests).
7. While signed in, switch the browser offline and click **Log out**. Expect a visible error rather than a false success. Restore connectivity and retry; logout should succeed.

Automated session-module tests cover correct/wrong passwords, protected profile requests, restoration deduplication, missing cookies, profile failures, logout, and retryable failures. They mock HTTP; the backend suite separately exercises real API/session behavior. Browser visual and cookie checks require the manual steps above when no browser connection is available.

## Configure Google sign-in locally

In Google Cloud Console / Google Auth Platform, configure branding, audience and test users (while the app is in Testing). Create an OAuth client of type **Web application**. Configure the authorized JavaScript origin `http://127.0.0.1:5173` for this repository's Vite server, and the actual HTTPS frontend origin for production. Origins must match the browser's scheme, hostname and port, with no path. If using localhost, Google recommends registering both `http://localhost` and `http://localhost:5173`; also change the Vite host and backend origin allowlist consistently. Use the existing 127.0.0.1 setup for the steps below.

The integration uses Google's official rendered button in popup mode with a JavaScript credential callback. It needs no authorized redirect URI, client secret, Google API access token or One Tap. Do not configure `/auth/google` as a Google redirect/form-post URL. See Google's [setup guide](https://developers.google.com/identity/gsi/web/guides/get-google-api-clientid) and [button guide](https://developers.google.com/identity/gsi/web/guides/display-button).

Stop existing development servers. In a backend PowerShell terminal, from the repository root:

```powershell
cd backend
$env:JWT_SECRET = (& .\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))")
$env:AUTH_COOKIE_SECURE = "false"
$env:AUTH_ALLOWED_ORIGINS = "http://127.0.0.1:5173,http://127.0.0.1:8000"
$env:GOOGLE_CLIENT_ID = "REPLACE_WITH_YOUR_WEB_CLIENT_ID.apps.googleusercontent.com"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

In a frontend PowerShell terminal, from the repository root:

```powershell
cd frontend
$env:VITE_GOOGLE_CLIENT_ID = "REPLACE_WITH_YOUR_WEB_CLIENT_ID.apps.googleusercontent.com"
npm.cmd run dev
```

Replace both placeholders with **the same Web application client ID**. `VITE_GOOGLE_CLIENT_ID` is public and embedded in the browser bundle; never use a client secret here. Restart Vite after changing it, and set it before `npm.cmd run build` for production. Backend environment files are not automatically loaded. No real IDs or credentials need to be committed. Without the frontend setting, the page explains that Google sign-in is unavailable and keeps email sign-in enabled.

The page loads only `https://accounts.google.com/gsi/client`, shares concurrent loads and offers retry after a load error or 15-second timeout. The credential callback sends JSON `{ "id_token": "<credential>" }` to `/auth/google` through the same Vite proxy. On success, the existing in-memory access token, protected `/auth/me`, refresh cookie and logout flow apply. Google credentials are never put in storage, URLs or logs. A `409 google_link_required` asks the traveler to use their existing sign-in method; no linking is attempted.

Google's ID-button API has no documented popup-close error callback. Closing the popup leaves email sign-in available. The page also provides **Cancel Google sign-in**, which cancels the local attempt and ignores late responses from that button; close the Google window separately. No One Tap prompt is requested. Logout also calls Google's `disableAutoSelect` when the SDK is available; it does not log the traveler out of their Google account.

## Test Google sign-in in the browser

These steps need a real configured client ID and allowed Google test account. Automated tests mock the SDK and HTTP, make no Google network calls, and do not verify real popup behavior or provider configuration.

1. Start both servers using the settings above and open http://127.0.0.1:5173/. Expect the official **Sign in with Google** button. Use Tab and Enter to activate it. At a 320px mobile viewport, check the button fits the card and all controls remain reachable.
2. Choose a Google account whose email is not registered in the local database. Expect one POST `/auth/google` returning `200`, then `/auth/me` returning `200`, and a welcome heading using the protected profile's name. Avoid copying request credentials or authorization headers into screenshots, logs or reports. Verify storage contains no tokens and the address bar never contains a Google credential.
3. Reload: expect `/auth/refresh`, then `/auth/me`, and the welcome view. Click **Log out**: expect `/auth/logout` returning `204`. Reload again and expect sign-in. Sign in with the same Google account again to check the returning-account flow.
4. With a different Google email that belongs to an existing email/password traveler, click Google sign-in. Expect `409 google_link_required`, a message to use the existing sign-in method, and no welcome view. Confirm the existing password still signs in. There is no automatic account linking.
5. Open the Google popup, then close/cancel it. Email fields must remain usable. Click **Cancel Google sign-in** to clear the local attempt, then retry Google sign-in. Under slow network throttling, completing Google authentication must disable both sign-in methods during the backend exchange and produce only one request.
6. To exercise backend failure, stop FastAPI after loading the page, then complete Google authentication. Expect an unavailable message and re-enabled controls. Restart FastAPI and retry. To exercise a network failure, block the `/auth/google` request in browser developer tools while leaving Google reachable, then complete authentication; expect a connection message. Clear the block afterwards.
7. Block `https://accounts.google.com/gsi/client` in developer tools and reload. Expect a load error (or the 15-second timeout), **Retry Google sign-in**, and usable email sign-in. Remove the block and retry. Stop Vite, remove `VITE_GOOGLE_CLIENT_ID` with `Remove-Item Env:VITE_GOOGLE_CLIENT_ID`, restart Vite, and check password sign-in, registration and reset navigation still work without Google configuration.

Frontend Google tests cover callback success, collision, invalid credentials, server/network errors, retry, duplicate submission, cancellation and stale callbacks, missing configuration, script loading failures, protected profile loading, refresh restoration and logout. The tests fail if application code touches localStorage or sessionStorage. Real Google authentication and visual/keyboard behavior still require the browser checks above.

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
