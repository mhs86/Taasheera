# Taasheera frontend

React + TypeScript + Vite. Registration, email/password sign-in, Google sign-in, and password reset are connected to the backend. Signed-in travelers see their name from protected `/auth/me` and can log out. The welcome view links to `/account`, where travelers can edit profile details, see sign-in methods, and (for email/password accounts) change their password. Google sign-in requires the public client ID configured below; email/password sign-in works without it.

## Run locally on Windows

First complete the one-time backend setup in `backend/README.md`. From `frontend/`, run `npm.cmd ci` once after cloning to install the locked frontend dependencies. Then use two PowerShell terminals, each starting at the repository root:

Terminal 1:

```powershell
cd backend
.\.venv\Scripts\python.exe dev.py run
```

Terminal 2:

```powershell
cd frontend
npm.cmd run dev
```

The public Google Web Client ID is already in `frontend/.env.development` and `backend/.env.development`. The backend development launcher reads its private JWT secret from Git-ignored `backend/.env.local`. No client ID or JWT setting needs to be typed into either terminal on later starts.

Open http://127.0.0.1:5173/sign-in#create-account. You can also follow Get started from the homepage. If port 5173 is occupied, stop the old Vite server before starting this one. Restart Vite after changing its configuration.

The browser calls `/auth`, `/passports`, `/profile`, `/activity`, and `/assistant` on the frontend origin. Vite forwards these requests to http://127.0.0.1:8000. No backend CORS allowance is needed. A production host must route all five prefixes to the API and use HTTPS with secure cookies. Use `127.0.0.1` consistently locally so the origin matches the backend allowlist. `/account` is a page; `/profile` is the protected API it uses.

## Edit traveler profile

Sign in, choose **Edit your account details** from the welcome view, then open the profile form at `/account`. All fields are optional. The country selects show names and send passport-style codes such as `LBN` and Germany's `D`; the source list is in `src/countries.ts`. Phone numbers need an international `+` prefix and are normalized by the backend when saved. Save replaces the complete profile, so a cleared field is saved as empty. A new traveler sees an empty-state message. The page also contains the existing **Sign-in methods** and **Change password** sections, with a link back to the welcome view. The account page does not send page or click audit events until the backend has an allowlisted account identifier; it never logs profile values.

The browser also sends allowlisted page visits and tagged clicks to authenticated `/activity/events`. It sends fixed identifiers only, never field values, link URLs, reset fragments, passwords, tokens, or Google credentials. Activity delivery is best effort and does not interrupt navigation. The backend records registration, sign-in, logout, and passport actions directly. Anonymous clicks are not stored because they cannot be linked to a verified traveler. Production routing must proxy `/activity` to FastAPI too.

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

The browser loads the public Google client ID from `/auth/config`. Configure
`GOOGLE_CLIENT_ID` on the backend; AWS changes take effect after API restart and
do not require rebuilding the frontend. Loading/configuration errors keep email
sign-in available and provide a retry button. Tokens remain in memory and
HttpOnly cookies; Google credentials and passwords are never stored in browser storage.

For an existing password account, sign in normally, open the account view at
`/account`, enter the current application password under **Connect Google**,
and use the official Google button. After successful linking the account view
shows the verified SSO email. Log out and use Google sign-in to return to that
same traveler account. An email collision on the signed-out flow still asks
the user to sign in with their existing method and link explicitly.

In Google Cloud Console / Google Auth Platform, configure branding, audience and test users (while the app is in Testing). Create an OAuth client of type **Web application**. Configure the authorized JavaScript origin `http://127.0.0.1:5173` for this repository's Vite server, and the actual HTTPS frontend origin for production. Origins must match the browser's scheme, hostname and port, with no path. If using localhost, Google recommends registering both `http://localhost` and `http://localhost:5173`; also change the Vite host and backend origin allowlist consistently. Use the existing 127.0.0.1 setup for the steps below.

The integration uses Google's official rendered button in popup mode with a JavaScript credential callback. It needs no authorized redirect URI, client secret, Google API access token or One Tap. Do not configure `/auth/google` as a Google redirect/form-post URL. See Google's [setup guide](https://developers.google.com/identity/gsi/web/guides/get-google-api-clientid) and [button guide](https://developers.google.com/identity/gsi/web/guides/display-button).

Stop existing development servers. Complete the one-time setup in `backend/README.md`, then start the backend from the repository root:

```powershell
cd backend
.\.venv\Scripts\python.exe dev.py run
```

In a frontend PowerShell terminal, from the repository root:

```powershell
cd frontend
npm.cmd run dev
```

The tracked development files already contain the same public Web application client ID. To change it in VS Code, edit `VITE_GOOGLE_CLIENT_ID` in `frontend/.env.development` and `GOOGLE_CLIENT_ID` in `backend/.env.development`, then restart both servers. Never put a Google Client Secret in either file. Production must supply its own `VITE_GOOGLE_CLIENT_ID` at build time and `GOOGLE_CLIENT_ID` and `JWT_SECRET` through deployment configuration; the development launcher is only for local HTTP. Without the frontend setting, the page explains that Google sign-in is unavailable and keeps email sign-in enabled.

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
7. Block `https://accounts.google.com/gsi/client` in developer tools and reload. Expect a load error (or the 15-second timeout), **Retry Google sign-in**, and usable email sign-in. Remove the block and retry. The automated tests cover missing Google configuration.

Frontend Google tests cover callback success, collision, invalid credentials, server/network errors, retry, duplicate submission, cancellation and stale callbacks, missing configuration, script loading failures, protected profile loading, refresh restoration and logout. The tests fail if application code touches localStorage or sessionStorage. Real Google authentication and visual/keyboard behavior still require the browser checks above.

## Test registration in the browser

1. Enter a name, a new email such as `traveler-test-1@example.com`, and matching passwords of at least 8 characters, such as `Travel-test-123`. Submit. Expect navigation to Sign In with an account-created message and no automatic sign-in. This creates a real traveler in the configured development database.
2. Return to Create Account and submit again using the same email and valid passwords. Expect an already-registered message. Email matching is case-insensitive. Password fields clear after each request, including errors.
3. Leave a required field empty, enter an invalid email, or enter mismatching passwords. The browser should block submission. To exercise an API validation response, use matching passwords of 73 ASCII characters: expect the password length message and no account creation. The limit is 72 UTF-8 bytes, so non-ASCII passwords may reach it sooner.
4. In browser developer tools, select a slow network preset, then submit with a new email. The button should say Creating account and stay disabled while the request runs. The fields are disabled too; repeated clicks should not create extra requests. Return network throttling to normal afterwards.
5. Stop FastAPI with Ctrl+C, keep Vite running, and submit a valid form. Expect a backend-unavailable message. For a browser network failure, select Offline in developer tools after loading the page, then submit. Expect a connection message. Restore the connection and restart FastAPI afterwards.

Requests time out after 15 seconds. A connection failure can occur after the server creates an account; the message explains that retrying may therefore report a duplicate email. Passwords are not written to storage or logs. The API returns public user details without a password hash.

## Test email OTP recovery

Use a private SMTP catcher for local testing or the verified SES sender on AWS
(see [authentication operations](../docs/AUTH_OTP_AWS.md)).

1. Register a password account, then open **Sign in → Forgot your password?**.
2. Submit its email, read the six-digit code, and enter it in **Code from your email**.
3. Verify the code, then choose and confirm a new password within five minutes.
4. Confirm the old password and all prior sessions fail; the new password signs in.
5. Repeat a used/expired/wrong code, duplicate submissions, and a resend after one
   minute. Resending invalidates the older code and reset grant. Five incorrect
   guesses lock that challenge. Google-only and unknown emails show the same generic
   confirmation but receive no OTP.

Codes expire in ten minutes. No recovery secret belongs in a URL, console output,
localStorage, or sessionStorage. Automated tests cover API failures, retries,
duplicate/stale callbacks, form validation and success; a real provider/browser
check remains separate from mocked HTTP tests.

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

The recovery screen requests an emailed six-digit OTP, verifies it, then accepts a new
password. Google-only users recover through Google. See [authentication operations](../docs/AUTH_OTP_AWS.md).
