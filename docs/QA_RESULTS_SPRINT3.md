# Sprint 3 branch QA — 31 October 2026

Review branch: `mohammad_admin_monitoring_privacy_sprint3`, based on `dev` at
`14ce6a6`. No merge to `dev`/`main`, deployment, live Google consent publication,
or live team alert is included in this local validation.

## Delivered behavior

| Ticket | Implementation and acceptance |
|---|---|
| CMPS271-126 / US 94 | `/backoffice` shows persisted applications by status, latest backend activity failures and pending erasures. Admin search/deletion is available. Agent failure reporting is explicitly pending the future agent workflow. |
| CMPS271-117 / US 88 | Traveler and admin deletion remove current profile, passport files/reviews, applications, sessions/refresh hashes, recovery credentials, access history and activity. Password or connected Google identity reconfirmation protects self-deletion. Failures return pending status and keep the account disabled until cleanup succeeds. |
| CMPS271-120 / US 120 | Storage-level passport image/review/assistant reads create an access record before returning content. Travelers view only their own history at `/account`; unaudited reads fail closed. |
| CMPS271-157/158/159 / US 135 | Official frontend/backend Sentry SDKs with strict privacy filters; bounded readiness probe and opt-in alert workflow; [monitoring runbook](MONITORING_RUNBOOK.md). External projects/channels still require operator configuration. |
| CMPS271-141 / US 1 | [Google production consent handoff](GOOGLE_CONSENT_RELEASE.md), preserving the existing OAuth client and origins. Publication requires the project/domain owner and has not been claimed complete. |

The existing authentication system is retained: signed short-lived JWT access
tokens, hashed rotating opaque refresh credentials in HttpOnly Strict cookies,
refresh replay detection, session revocation and current database roles/status.
Additional checks reject malformed JWT claims, cross-account deletion hints/cookies,
and stale browser account switches. All private APIs are covered by an anonymous
request inventory test; bootstrap/recovery/config/health endpoints remain public.

The application registry supplies real draft creation/list/read and server-controlled
status storage. It does not implement embassy submission or an agent processor.
Demo progress/failure rows are explicitly synthetic local fixtures.

## Verification

| Check | Result |
|---|---|
| Complete backend suite, SQLite and disposable PostgreSQL 17 | 548 passed, no skips |
| Frontend unit and DOM interaction suite | 113 passed |
| Real Chromium + Vite + FastAPI/OCR browser flows | 2 passed |
| ESLint, TypeScript and production Vite build | Passed |
| New privacy/monitoring interaction tests after final timestamp display fix | 7 passed |
| Launcher tests, including exited-process port restart | 3 passed |
| PostgreSQL `alembic check` | No new upgrade operations detected |
| Python compilation and `git diff --check` | Passed |
| Production Dockerfile build | Passed |
| Container smoke | Non-root execution, migrations, OCR readiness, registration/login, private APIs, role denial, application creation and deletion passed |
| Live isolated localhost preview / readiness probe | Passed on 8000/5173; restart freed the required ports and preserved unrelated listeners |

Coverage includes input-validation/JWT units; feature/API tests; ownership and
role matrices; session rotation/replay/revocation; profile/password/Google linking
regressions; passport/OCR tests; DB/file/API integration; fresh/old-schema adoption,
upgrade/downgrade and model drift; deletion during an in-flight upload; cleanup
failures and startup retries; audit-write failures; duplicate submits, cancellation,
pagination, loading/error states; cross-tab authentication serialization; cookie
flags and absence of browser token storage; and a narrow-screen dashboard check.

Sentry's actual SDK envelope is tested through an offline transport to verify
privacy filtering. Uptime failure retries/webhook payloads are tested with an
offline transport; a real localhost readiness probe also passed. Browser tests
generate specimen images and disposable accounts, then exercise deletion through
the real browser and API together.

QA found and fixed accessible country-selector labels, a sign-in/deletion race,
an exited-process port-restart issue, and PostgreSQL timezone-column drift. The
environment's temporary Docker disk pressure was resolved by removing task-created
images/build caches and using a smaller disposable test database container.

## Limits and external follow-up

- No real Google owner login, domain registration/verification, or consent publication
  was available. Follow the owner checklist and perform real popup acceptance before release.
- Live Sentry delivery, team notification routing and the scheduled external uptime
  job need operator-provided projects/DSNs/webhook/URL. No credentials or real alerts
  were fabricated. The isolated preview disables external services by default.
- Agent failure ingestion waits for the actual agent backend, as specified by the ticket.
- Deletion covers the managed live DB and owner folders. Existing infrastructure logs
  and historical backups need the operator retention/restore policy in the runbook.
- The Lambda image was not built locally in this restricted environment; its existing
  CI build remains in place. No AWS resources or deployment settings were changed.
- Browser execution covered Chromium, with a mobile viewport check; it does not
  establish cross-browser certification, formal load capacity, or a penetration audit.
- Backend tests emit the existing Starlette/httpx deprecation warning; no test failure
  is suppressed. Tests without `TEST_POSTGRES_URL` explicitly skip PostgreSQL cases.

## Local handoff

Use [the startup commands and acceptance checklist](LOCAL_FEATURE_TESTING.md).
The preview uses separate ignored state under `backend/storage/feature-preview/`.
Do not run migrations against the existing database just to test this branch.
No existing `.env.local`, OAuth client ID, AWS deployment workflow, domain,
database or upload directory was changed by QA.

Open `http://127.0.0.1:5173/sign-in`; admin dashboard: `/backoffice`.
Synthetic demo accounts: `qa-admin@example.com`, `qa-traveler@example.com`, and
`qa-delete-me@example.com`; password: `Local-preview-only-123!`.
Restarting with `--seed-demo` recreates deleted demo accounts; omit that flag when
checking deletion across restarts. The user's branch testing precedes any merge
or deployment.
