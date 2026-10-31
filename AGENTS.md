# Ta'asheera (تأشيرة): shared project context

Coding agents read this file at session start. Update it in the same branch when
stack, layout, commands or workflow change. Keep it concise (under about 200 lines).
Personal preferences belong in ignored local files, never here.

## Product and rules

Group 7's university Software Engineering project: an AI visa application agent.
Travelers sign in, accept privacy policy, select destination/type/nationality,
upload and confirm passport fields, complete document/intake checks, review a
cover letter and embassy form, and explicitly confirm any submission. Planned
submission modes: L1 PDF packet; L2 portal until review; L3 traveler CAPTCHA handoff;
L4 manual guide. Status tracking and Telegram/email notifications follow later.

- Passport/document storage is private; authenticate and check ownership on every read/write.
- Never submit to an embassy without explicit traveler confirmation.
- AI advice carries a not-legal-or-immigration-advice notice.
- Use specimen passports/synthetic data in tests; never commit real passports,
  secrets, `.env` files, local databases, or private activity logs. This repo is public.

## Team and workflow

Group 7: Mohammad Sharafeddin, Dani Salman, Ahmad Zeid, Ahmad Al Hariri.
Sprint 1 supplied auth, AWS/CI, frontend shell and passport OCR. Sprint 2 added
profile/password/session management and admin roles/user management. The current
feature branch adds the Sprint 3 admin monitoring/privacy work (US 94, 88, 120,
135 follow-ups, and the US 1 Google consent owner checklist).

- `main` is production; merge only tested `dev` work into it.
- Fetch `dev` explicitly (`git fetch origin refs/heads/dev:refs/remotes/origin/dev`)
  before branching; a narrow workspace fetch may leave that local reference stale.
- `dev` is integration. Branch from `dev`; convention `<name>_<feature>_sprint<N>`.
- Reference story numbers in review descriptions and explain behavior and validation.
- The original Sprint 3 work required local testing before integration. On 31 October
  2026 the user explicitly authorized releasing the Google sign-in, missing welcome
  links and admin-by-email fixes directly to production. Keep the tested source on
  `mohammad_prod_auth_admin_sprint3`; do not move dev/main merely to trigger deployment.
- The user separately authorized US 1 public policy pages on AWS. The scoped publisher
  updates public assets/homepage links without releasing Sprint 3 API features.
- Do not modify existing deployment/environment settings to test new features.

## Stack and layout

| Area | Current implementation |
|---|---|
| API | Python 3.12, FastAPI router factories, SQLModel, Pydantic v2, uvicorn |
| Auth | bcrypt, PyJWT access tokens in memory, rotating opaque HttpOnly refresh cookie, google-auth |
| Authorization | Database traveler role (traveler/support/admin) and status (active/suspended), checked each request |
| Database | SQLite on persistent EBS; psycopg PostgreSQL driver; Alembic owns schema changes |
| Frontend | React 19, TypeScript, Vite, React Router data routes, sonner, plain CSS |
| Styling | DM Sans + Space Grotesk, CSS variables; no Tailwind or adopted query framework |
| Files | Private owner folders locally; private S3 storage still a future adapter |
| OCR | Tesseract/pytesseract; MRZ locator/repair/check digits; vision fallback proposed |
| Assistant | google-genai Gemini adapter; backend-only key; no agent tools/queue yet |
| Monitoring | JSON request/security logs; ActivityEvent + private JSONL; opt-in Sentry and uptime workflow |
| Tests | pytest/API/security/OCR/migrations/PostgreSQL; Node DOM interactions; Playwright Chromium/API flows |
| Hosting | Non-root backend container and Lambda image; existing AWS workflows; Render demo and Netlify/Vercel configs |

`backend/app/` contains router factories and services; `backend/alembic/` migrations;
`backend/tests/` API/unit/integration tests; `backend/manage.py` operator role assignment;
`backend/preview.py` isolated preview; `backend/retry_erasures.py` operator cleanup;
`backend/scripts/` demos/probes; `frontend/src/`, `frontend/tests/`, `frontend/e2e/`;
`docs/` operational guides; `deploy/aws/` existing host deployment scripts.
Python runtime/test dependencies are pinned in requirements.lock/requirements-dev.lock.

## Local commands and routes

Existing local development is unchanged: from backend, create/activate `.venv`,
install `requirements-dev.lock`, `python dev.py setup`, then `python dev.py run`.
The setup preserves an existing ignored local JWT secret; run loads it and the
public Google ID, applies migrations and serves 8000. Frontend: `npm ci`, `npm run dev`
on 5173. Production supplies environment config, `APP_ENV=production`, secure cookies,
exact HTTPS origins, and `SCHEMA_AUTO_CREATE=false`. Only tests use create_all.

For this feature use the isolated preview instead: `python preview.py run --seed-demo
--free-ports` (on one command line) from backend. It starts API and frontend with a
separate DB/secret/files under ignored `backend/storage/feature-preview-sprint3/`, never loads
`.env.local`, and stops listeners only on its chosen API/web ports when requested.
Optional `--api-port`/`--web-port` configure matching proxies/origins. Mail/Gemini are
disabled; Sentry requires explicit `--enable-monitoring` plus exported DSNs.
Seeded credentials and Windows/macOS/Linux instructions: `docs/LOCAL_FEATURE_TESTING.md`.

UI routes: `/sign-in`, `/reset-password`, `/account`, `/passport/:uploadId`,
`/apply`, `/admin` (existing staff UI), `/backoffice` (monitoring). API prefixes:
`/auth`, `/profile`, `/sessions`, `/passports`, `/activity`, `/assistant`, `/applications`,
`/admin` (backend; browser calls `/admin-api`). Vite/Netlify proxy APIs through the browser origin; cookies stay first-party.
Public APIs are limited to sign-in/registration/recovery/refresh/logout/config and
minimal health checks; traveler data APIs require bearer auth. Admin APIs require admin.
The frontend discovers staff identity via `/admin/me`; `/auth/me` retains its old schema.

Checks: backend `python -m pytest -q`; frontend `npm test`, `npm run lint`,
`npm run build`, `npm run test:e2e` (install Chromium first). Browser tests need the
backend Python on PATH or `TAASHEERA_TEST_PYTHON`, use 8100/5273 and separate e2e-preview-sprint3-*
storage. `TEST_POSTGRES_URL` must point to a disposable test DB with create/drop DB
privilege; absent it, PostgreSQL cases are skipped. CI includes both DBs and images.

## Conventions and decisions

- Follow router factories; request bodies use Pydantic `extra="forbid"`.
- Validate environment configuration at startup (`app/config.py`).
- Errors/logs must omit submitted values, tokens, request bodies and document fields.
- Every feature needs meaningful tests; lint/tests/build gate review.
- Prefer familiar libraries; keep the application demoable by the four-person team.

1. FastAPI keeps typed APIs and OCR/AI in Python; no separate Node backend.
2. React/Vite/TypeScript catches API/UI mistakes with a small build setup.
3. MRZ-first extraction locates lines and repairs look-alikes by checksums within a
   six-second retry budget. Check digits miss some errors, so confirm every field.
   PassportEye was replaced; vision-model fallback remains proposed.
4. Uploaded images are re-encoded JPEGs to strip EXIF/GPS, with random IDs under
   `<traveler_id>/<upload_id>`. Production uploads need durable private storage.
5. React Router owns paths/404/error boundaries; same-origin API proxies carry cookies.
6. Plain CSS/sonner adopted; Tailwind and TanStack Query remain unadopted.
7. Sign-in/reset forms use hash fragments for form selection/reset tokens; tokens
   are scrubbed from the address bar. Passport APIs share auth's traveler dependency.
8. `dev.py setup` preserves the existing JWT secret; local HTTP settings never change production.
9. Activity timestamps/owners are server controlled. Browser page/control events
   are allowlisted and contain no free text. Database events are authoritative;
   per-owner JSONL mirrors are best effort and private. Anonymous failures have no owner.
10. Alembic versions deployment/local schemas and adopts only exact known old schemas.
    CI checks backend/frontend/OCR/PostgreSQL/images; request logs use route templates.
11. Netlify builds frontend/dist and generates HTTPS API rewrites from BACKEND_URL;
    backend and private durable file storage remain separate requirements.
12. Render's free demo disables uploads; ephemeral files and expiring DBs cannot store real passports.
13. Passport review saves only confirmed, owner-scoped fields; frontend/passport/fields.ts
    defines form rules, per-field trust, validation and edited state.
14. Assistant context comes only from the caller's latest confirmed passport. One
    backend Gemini adapter, bounded timeout/retry and per-traveler rate limits; chat
    history stays in the page. Free-tier Google may use prompts for improvement/human
    review: specimen/demo data only until a suitable paid/provider arrangement exists.
15. Lambda deployment workflow packages FastAPI/Tesseract with the AWS adapter; AWS
    OIDC/ECR/Lambda/API Gateway and durable storage remain external prerequisites.
16. Google identities use verified sub, never email alone for linking. Existing password
    users explicitly link with bearer auth/current password, or prove a verified Google
    ID token AND their existing password at `/auth/google/link-login`. GOOGLE_CLIENT_ID is public.
17. Email recovery: ten-minute/five-attempt OTP, five-minute reset grant, revoke all
    sessions on reset; no Google-only password enabling. Limits are DB backed.
    SES is sandboxed. OAuth/SES administration uses sharafm032@gmail.com; project
    owner remains mhs86@mail.aub.edu. See docs/AUTH_OTP_AWS.md and GOOGLE_SSO_AWS.md.
18. Signed-in password change keeps the current session and revokes others;
    Google-only travelers cannot change a disabled password.
19. Profile is a separate traveler-owned row; phone normalizes to E.164, past birth
    dates and country-code shapes are validated; Traveler.name stays the display name.
20. `/account` groups profile, sign-in methods, password, sessions and privacy controls.
    Countries use UN M49 names plus ICAO codes (D, RKS, TWN).
21. Sessions keep short device labels and UTC creation/last-active dates; legacy
    dates may be null. Last-active changes on refresh; revocations apply next request.
22. Roles/status use named portable CHECK constraints, never JWT role claims or
    sign-up roles. First admin is promoted with manage.py; suspended users cannot sign in.
23. Admin changes lock actor/target rows in ID order, recheck actor privileges,
    reject self-suspension/self-role change, revoke sessions on status changes,
    and commit with metadata-only role/status events. No passport/profile fields in admin APIs.
24. Guided application chat uses validated JSON questionnaires and a pure deterministic
    flow engine (`applications/flow.py`), not LLM-chosen questions. API `/applications`,
    UI `/apply`; only current/previous answers are writable, and each copy is saved.
25. Destination/visa/group size select the question file before creation. Group size
    is recorded until group applications arrive; the sidebar derives place/date from answers.
26. Prefill uses the owner's latest confirmed passport/profile, recomputed server-side
    when accepted. ConfirmedPassportFields applies profile country/birth-date rules;
    OCR output stays looser. Suggestions/editing never change the original profile.
27. Existing admin UI is `/admin`, API is `/admin-api/*` rewritten to `/admin/*` by
    Vite/nginx/Netlify. Preserve its layout guard, user search/filter/suspend/role controls.
28. Sprint 3 privacy/monitoring: aggregate the existing Application statuses
    (DRAFT, INELIGIBLE, ANSWERS_COMPLETE), and erase ApplicationAnswer copies too. Storage
    callbacks audit every passport image/review/assistant read before returning bytes.
    Portable per-owner file locks serialize requests with deletion across workers
    sharing local storage. Erasure first suspends/revokes and persists AccountErasure,
    then removes owner folders and related rows; 204 means complete, 202 means retry
    pending. Startup/operator retries finish cleanup; pending accounts cannot reactivate.
    Sentry uses strict metadata allowlists; uptime is opt-in. Google production consent
    publication needs the owner's real domain/account (docs/GOOGLE_CONSENT_RELEASE.md).
    See docs/MONITORING_RUNBOOK.md for log locations, retries and service configuration.
29. Public consent pages are standalone `frontend/public/privacy.html` and `terms.html`,
    with shared legal.css and links in index.html outside the React root. No auth/JS
    is needed. `deploy/aws/publish_public_policies.py --execute` uses AWS CLI/SSM to
    update only these public assets and the existing homepage, with backup/rollback.
    These pages were published via CloudShell and HTTPS-verified on 31 October 2026.
    Google ownership/branding verification remains pending; see docs/GOOGLE_APP_DOMAIN.md.
30. Admin users can find an existing account by primary or linked Google email and
    confirm its promotion under `/admin`. Lookup never grants privileges; grant rechecks
    actor/target locks, account ID, ambiguity and status. No unverified-email invitations.
    `deploy/aws/release_production.py --execute` uses authenticated AWS CLI/SSM, preserves
    exact existing private config, backs up SQLite and verifies client/API/policies.
    Optional `--admin-email` uses manage.py on the host; no hardcoded app admin allowlist.
    See docs/PRODUCTION_AUTH_ADMIN_FIX.md for release steps and QA status.
31. Production builds use build_images.py: API then web, with COMPOSE_BAKE=false;
    migration shares taasheera-api. Retry only disconnected sessions once. Build logs
    stay private; never stop Docker/prune images to recover. Startup uses --no-build.

## Personal instructions

Use ignored local preference files; CLAUDE.local.md is already ignored.
