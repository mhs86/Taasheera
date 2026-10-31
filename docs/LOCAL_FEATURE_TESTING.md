# Sprint 3 local feature testing

Branch: `mohammad_admin_monitoring_privacy_sprint3`, based on `dev`. Do not merge
or push this work into `dev` or `main` until the user finishes testing. No deployment
is part of this change. Existing deployment workflows and environment files stay in place.

## Start the isolated preview

Requirements: Python 3.12+, Node.js 24, and Tesseract on PATH (the same OCR
requirement as the existing application). Run these from your Taasheera checkout.

macOS/Linux:

```bash
git fetch origin
git switch mohammad_admin_monitoring_privacy_sprint3
cd frontend
npm ci
cd ../backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.lock
python preview.py run --seed-demo --free-ports
```

Windows PowerShell:

```powershell
git fetch origin
git switch mohammad_admin_monitoring_privacy_sprint3
cd frontend
npm ci
cd ../backend
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.lock
.\.venv\Scripts\python.exe preview.py run --seed-demo --free-ports
```

Open **http://127.0.0.1:5173/sign-in**. The launcher starts both processes; Ctrl+C
stops both. `/backoffice` is the admin dashboard, `/account` holds deletion and
passport access history, and `/my-applications` creates and lists traveler drafts.
API documentation is at **http://127.0.0.1:8000/docs**; its private operations require
a bearer access token. Login, registration, refresh-cookie exchange, recovery,
public Google client configuration, and minimal health checks are deliberately public.

`--free-ports` stops listeners on **8000 and 5173 only**, then starts the preview.
Unrelated ports are preserved. Choose other ports with
`--api-port 8001 --web-port 5174`; their matching proxy/origin settings are automatic.
Without `--free-ports`, occupied ports produce a clear error and no process is stopped.

All preview state is under ignored `backend/storage/feature-preview/`: a separate
SQLite database, private uploads, activity mirrors, locks and a persistent local
JWT secret. `.env.local`, the existing database, existing uploads and deployed
settings are not loaded or modified. This is a fresh local dataset; existing
accounts are not copied. Mail and Gemini calls are disabled in the preview.
Sentry is disabled by default; `--enable-monitoring` opts into DSNs exported in
the shell, without loading any production environment file.

`--seed-demo` adds only synthetic data, and is safe to repeat:

| Account | Purpose |
|---|---|
| `qa-admin@example.com` | Admin dashboard and user deletion |
| `qa-traveler@example.com` | Drafts, passport upload and access history |
| `qa-delete-me@example.com` | Disposable account for deletion |

All three use **`Local-preview-only-123!`**. They exist only in the preview
database. Demo applications include explicit sample DRAFT, IN_PROGRESS and FAILED
rows; no agent or embassy submission actually runs. Create a fresh traveler from
the registration form to test with an empty account. The seed command will recreate
a deleted demo user on the next launch, so verify deletion before restarting with
`--seed-demo`, or restart without that flag.

To promote an account you created in this preview:

```bash
python preview.py admin --email your-local-account@example.com
```

## Acceptance checklist

1. Sign in as the traveler; reload and confirm the cookie restores the session.
   Create a draft at `/my-applications`. The destination and visa type persist.
2. Upload a **synthetic specimen image**, view it, and confirm its review fields.
   At `/account`, click **Refresh access history**. Image, extraction, review and
   assistant-context reads are recorded before content is returned. Another
   traveler's upload ID returns 404; another traveler's audit history is inaccessible.
3. Sign out, then sign in as the admin. `/backoffice` shows persisted status totals
   and newest backend failure metadata. Search users, select a disposable traveler,
   and confirm deletion with `DELETE`. Admin accounts cannot be deleted until
   their role is transferred; support and traveler accounts cannot call admin APIs.
4. As a disposable traveler, open `/account`, enter the current password and type
   `DELETE`. For Google-only accounts, reconfirm the connected Google identity.
   Success clears the cookie, and every existing access/refresh session stops
   working. Profile, files, applications, reset credentials, access history and
   activity are removed, while other accounts remain intact.
5. If cleanup fails, the API returns **202 pending**, immediately suspends the
   account and revokes sessions. It returns **204 only after completed erasure**.
   Pending accounts cannot be reactivated or assigned roles. Startup retries
   erasures; local operators can also run `python preview.py retry-erasures`.
6. Test narrow-screen dashboard layout and keyboard access to search, confirmation
   and pagination. Cancellation must not send a delete request.

The application registry is intentionally small: travelers can create/list/read
drafts; status is server controlled. This sprint does not implement the embassy
agent, submission, or fabricate agent failures. Existing applications stored by a
future workflow should use `VisaApplication`; `/admin/monitoring` already aggregates
all six stored lifecycle statuses. See the monitoring runbook for live services.

## Automated verification

With the backend venv activated:

```bash
cd backend
python -m pytest -q
cd ../frontend
npm test
npm run lint
npm run build
npx playwright install chromium
npm run test:e2e
```

Run the first `cd backend` from the repository root. For browser tests, the active
Python must have the backend requirements, or set `TAASHEERA_TEST_PYTHON` to its
absolute path. If Chromium is already installed, export
`PLAYWRIGHT_CHROMIUM_EXECUTABLE` to its executable instead of downloading a browser.
Browser tests start their own API/frontend on **8100/5273** and use a different
ignored `backend/storage/e2e-preview/` dataset. They never reuse an existing server.

Set `TEST_POSTGRES_URL` to a **disposable test PostgreSQL database** to include the
PostgreSQL suite. Its user must be able to create/drop temporary databases. Tests
perform migrations and destructive fixture cleanup there; never point it at a
development or production database. Without it, PostgreSQL cases are explicitly skipped.

CI runs API/unit/security/migration/OCR tests, frontend interaction tests, lint,
TypeScript/build, real Chromium/API flows, PostgreSQL schema drift checks, and
container smoke checks. The browser flow uses generated specimen data only.
