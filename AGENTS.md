# Ta'asheera (تأشيرة): shared project context

Coding agents (Claude Code, Codex, Cursor, etc.) read this file at the start of every session.
It's shared by the whole team through git. Personal preferences don't belong here (see the end of this file).

## Keeping this file current (agents: follow this)

This file only helps if it matches reality. As part of any change you make:

- If the change affects anything described here (stack, layout, commands, workflow, conventions,
  a decision), update this file **in the same branch/PR**.
- If you notice something here is stale or contradicts the code, fix it, or tell the user if you're unsure.
- When a tentative stack item gets adopted or replaced, change its status and add a Decisions log entry.
- Keep it concise (under ~200 lines). Remove outdated content rather than piling on.

## What we're building

Ta'asheera ("visa" in Arabic) is a web-based AI visa application agent, a Group 7 project for a
university Software Engineering course, inspired by Veeza AI (YC F26). The traveler uploads a
passport, answers the embassy's questions, uploads supporting documents, and the agent checks
everything, fills the embassy's application, and prepares it for the traveler to submit.

End-to-end flow (from the team's activity diagram):

1. Sign in (Google, or email + password). Accept the privacy policy on first visit.
2. Choose destination, visa type and passport nationality. The app loads the embassy's requirement
   profile and creates a DRAFT application with a document checklist.
3. Upload passport. Check image quality, read the MRZ (vision-model fallback if the MRZ checksums fail),
   and have the traveler confirm the extracted fields.
4. In parallel: upload supporting documents, and a chat intake where the agent asks the next
   question based on answers so far, until the trip profile is complete.
5. Completeness and cross-document consistency check. Each issue links to where it can be fixed.
6. Generate a cover letter and map answers to the embassy form. The traveler reviews field by field,
   pays, and explicitly confirms.
7. Submission by embassy automation level:
   **L1** fill the official PDF and build a print-ready packet ·
   **L2** fill the online portal (no CAPTCHA) and stop at its review page ·
   **L3** fill the portal until a CAPTCHA, hand off to the traveler, then resume ·
   **L4** not automatable, so generate a field-by-field manual guide.
8. Track status (SUBMITTED → DECIDED) with Telegram/email notifications.

Product rules that come from the domain:
- Passport and document data is sensitive. Store it privately and check ownership on every request.
- Nothing is ever submitted on the traveler's behalf without their explicit confirmation.
- AI output shown to travelers carries a "not legal or immigration advice" notice.

## Team and workflow

Group 7: Mohammad Sharafeddin, Dani Salman, Ahmad Zeid, Ahmad Al Hariri.

Current sprint: **Sprint 3** (Oct 20 to Nov 3). Goal (from Jira): Google or email sign-in and a reset code that
really arrives; an assistant that knows the whole application and acts with the traveler's approval; travelers
manage all their applications from one dashboard; admins monitor applications and delete users; merging to
main reaches the live site.
Areas: Sharafeddin (admin pages, logging, monitoring, account deletion), Al Hariri (sign-in and account
security), Zeid (agentic assistant, deploy pipeline), Salman (applications dashboard US 19, 20, 79;
backups US 126; branch protection). Testers (also the GitHub reviewer): Salman tests Zeid, Zeid tests
Al Hariri, Al Hariri tests Sharafeddin, Sharafeddin tests Salman. The admin files now belong to Sharafeddin.
Shared code: Sharafeddin owns the sign-in, Google and reset routes. Ending a traveler's other sessions
goes through `revoke_other_sessions` in `backend/app/auth.py`; don't write a second one. The suspended-user
check belongs in the single current-traveler loader. Alembic must keep one head: before merging a PR
that adds a migration, point its `down_revision` at the current `dev` head.
The product backlog (US 1 to US 133, 15 epics) is a guide and will change. Update this section each sprint.

Git:
- `main` is production. It only receives merges from `dev` once the sprint's work is tested.
- `dev` is the integration branch. Branch off `dev` for each feature and PR back into `dev`.
- Branch naming (existing convention): `<name>_<feature>_sprint<N>`, e.g. `hariri_auth_sprint1`.
  Reference user story numbers (e.g. "US 7") in PR titles/descriptions.
- Keep PRs focused on one feature. Say *why* in the PR description, not just what.
- Never commit secrets, `.env` files, local databases, or real passport images (use specimen
  passports or synthetic MRZ data for tests).

## Tech stack

Status key: **in use** = already in the code · **proposed** = tentative recommendation.

| Area | Choice | Status | Why |
|---|---|---|---|
| Backend | Python, FastAPI, SQLModel, Pydantic v2, uvicorn | in use | Typed validation, auto OpenAPI docs; Python is where the OCR/AI libraries are |
| Auth | bcrypt, PyJWT access tokens in memory, rotating HttpOnly refresh cookies, google-auth; roles stored on the traveler row | in use | See `backend/app/auth.py`, `google_auth.py`; `/admin` gate in `admin_api.py` |
| Frontend | React 19, TypeScript, Vite, ESLint | in use | Mainstream, fast dev loop, types catch API mistakes |
| Database | SQLite on persistent AWS EBS; PostgreSQL driver and Alembic migrations | in use | `migrate.py upgrade` versions the current schema; local startup runs migrations; only tests use `create_all` |
| File storage | Owner-scoped local folder in dev; private S3-compatible bucket before production | local in use; bucket proposed | Passports must never sit in a public folder or on an ephemeral server disk |
| Passport OCR | Tesseract via pytesseract, MRZ located and repaired by our code (`backend/app/passport/`); vision LLM fallback when check digits fail | in use (vision fallback proposed) | MRZ check digits let us verify a read instead of trusting it |
| LLM | Google Gemini (`gemini-3.5-flash-lite`, free tier) via the official `google-genai` SDK, called only from the backend (`backend/app/assistant.py`); tool use later | in use (assistant); tool use proposed | Free for the course; keys never reach the browser; the provider sits behind one adapter function, so it can change without touching the endpoint |
| Frontend routing, toasts | React Router (data router: routes, 404, error boundaries), sonner (toasts via `src/api.ts`) | in use | Page crashes and failed API calls show a page or a toast instead of a blank screen |
| Frontend styling | Plain CSS with custom properties (`src/index.css` tokens); DM Sans + Space Grotesk, layout modelled on Migraide (simple, no pricing) | in use | Small site, no extra build tooling; auth screens use the same site font and scoped form styles. Tailwind not adopted (see decision 6) |
| Frontend data fetching | TanStack Query (loading/error states) | proposed | Adopt once pages load real data |
| Backend hosting | One AWS EC2 host (`us-east-1`) running the non-root FastAPI + Tesseract container with Docker Compose, SQLite and passport files on encrypted EBS (`deploy/aws/`); Render blueprint and Lambda image kept as alternatives | live at https://d3vh2ppjrlwxee.cloudfront.net; its config is in open PR #6 (not on `main`) | Cheapest always-on setup that keeps passport files on persistent private disk |
| Frontend hosting | Nginx container on the same EC2 host serving the Vite build behind CloudFront; Netlify config (`netlify.toml`, `docs/NETLIFY.md`) kept as rollback | in use | One origin proxies `/auth`, `/passports`, `/profile`, `/sessions`, `/activity`, `/assistant`, `/applications`, and `/admin-api` (to `/admin`), so cookies stay first-party. A new API prefix must be added to `vite.config.ts`, `write-netlify-redirects.mjs` and `deploy/aws/nginx.conf`, and must not match a page path |
| Domain | CloudFront hostname with viewer HTTPS | in use; custom domain not configured | Auth cookies work on the browser origin; Google OAuth origins must list this hostname |
| CI/CD, observability | GitHub Actions CI, Lambda image deployment workflow, JSON request logs; Sentry, uptime check | CI/logs in use; Lambda workflow awaits AWS setup; monitoring proposed | CI builds both backend images; `deploy-backend.yml` pushes the Lambda image on main backend changes after OIDC setup. Public ECR rate-limits GitHub runners (HTTP 429), so CI keeps the Lambda adapter image in the Actions cache and retries the pull only when the cache is empty |
| User activity logging | SQLModel `ActivityEvent` plus private per-traveler JSONL mirrors in `backend/storage/activity-logs/` | in use | Auth and passport actions are recorded on the backend; allowlisted frontend page/control events use authenticated `/activity/events` |
| Later sprints | Playwright (Python) for L2/L3 portal filling; pypdf for L1 PDF forms; a job queue (e.g. arq + Redis) for long agent runs; Telegram Bot API; transactional email | proposed | Not needed yet |

Layout: `backend/app/` (router factories included by `main.py`; `applications/` holds the flow engine and
one question file per destination in `applications/questionnaires/`), `backend/alembic/`
(schema revisions), `backend/manage.py` (operator commands such as `set-role`),
`backend/scripts/` (passport demo), `backend/tests/`,
`frontend/src/`, `frontend/tests/`. Deployment plan: `docs/DEPLOYMENT_PLAN.md`.

Local Windows setup is in `backend/README.md` and `frontend/README.md`. From `backend/`,
create `.venv`, install `requirements-dev.lock`, run `python dev.py setup` once, then
`python dev.py run` to apply database migrations, load the ignored local JWT secret and
public Google client ID, and serve on port 8000. From `frontend/`, run `npm ci` and `npm run dev` on port 5173.
Check with backend `python -m pytest -q` and frontend `npm test`, `npm run lint`,
`npm run build`. The authenticated API proxies `/auth`, `/passports`, `/profile`, `/sessions`, `/activity`, `/assistant`, `/applications`, and `/admin-api` through Vite;
the standalone passport demo is separate. OCR needs system Tesseract on `PATH`. The assistant needs `GEMINI_API_KEY` (free from Google AI Studio): locally as a line in Git-ignored `backend/.env.local`, which `dev.py run` loads; on Render in the dashboard (`render.yaml` names it with `sync: false`). **Never commit the key: this repository is public.** Without it `/assistant/messages` returns 503 and everything else works.
`dev.py run` and deployments both run `python migrate.py upgrade` before the API starts; deployments
set `APP_ENV=production` and `SCHEMA_AUTO_CREATE=false`. Give an existing account a role with
`python manage.py set-role --email <email> --role admin`.

## Conventions

- Match the style of the surrounding code. New backend features follow the router-factory pattern.
- Validate every request body with a Pydantic model using `extra="forbid"`.
- Config comes from environment variables, validated at startup (see `app/config.py`).
- Don't leak sensitive values in errors or logs (see how `main.py` strips input values from 422 responses).
- Every endpoint touching a traveler's data or files checks that the authenticated traveler owns it.
- Add or update tests with every feature. Lint, tests and build must pass before a PR merges.
- Prefer well-known libraries over custom code. This has to be demoable and maintainable across four sprints.

## Decisions log

What we decided, why, and what we rejected. Newest at the bottom. Add an entry when a decision is made.

1. **FastAPI backend.** Python fits the OCR/LLM work. *Rejected: a Node backend, which would split
   the AI tooling across two languages.*
2. **React + Vite + TypeScript frontend.** Mainstream and typed.
3. **MRZ-first passport extraction.** OCR only the MRZ (fixed ICAO 9303 format), then repair it:
   look-alikes corrected by position, `<` misread as `K` restored, and in alphanumeric fields a
   single look-alike swap accepted only if it's the one swap passing both check digits. Status is
   verified / needs_review / unreadable. *Rejected: full-page field OCR (nothing to verify against).*
   *Replaced: PassportEye*, whose MRZ locator failed on a real passport with a patterned background;
   we now OCR the page with Tesseract and find the MRZ lines ourselves, retrying rotations and scales
   within a 6 s budget. Note: check digits miss some errors (e.g. `L`/`1`, `G`/`6` are equal mod 10),
   so the traveler confirms every field.
4. **Passport images:** re-encoded to JPEG on upload (fixes rotation, strips EXIF/GPS), stored under
   `<traveler_id>/<random id>`, so reads are owner-scoped by construction. Local disk in dev, private bucket in prod.
5. **Path-based routing with React Router.** Real paths (`/faq`, `/sign-in`) so unknown URLs can show
   a 404 and the static host can serve one `index.html` for everything. API calls go to the frontend
   origin and are proxied (Vite in dev, host rewrites in production), so auth cookies stay first-party.
   *Rejected: hash-only routing, which cannot 404.*
6. **Plain CSS with custom properties, sonner for toasts.** Design tokens in `src/index.css`, no CSS
   build step; sonner is a small, well-known toast library. *Rejected: Tailwind (was proposed),
   which adds tooling and class-heavy markup that a site this size doesn't need.*
7. **Sprint 1 integration.** The auth pages mount at `/sign-in` and `/reset-password` in the site
   router; hash fragments select the auth form and carry reset tokens. The main FastAPI app mounts
   the passport endpoints with the same authenticated traveler dependency used by `/auth/me`.
   Local passport images default to ignored `backend/storage/passports/`; production still needs
   private bucket storage.
8. **Local auth setup.** `backend/dev.py setup` creates an ignored, persistent JWT secret;
   `dev.py run` loads it with the public development Google client ID and local HTTP cookie
   setting. The frontend reads the public client ID from `/auth/config`. Registration
   returns to the sign-in form with a success message, and the create-account password can be shown
   or hidden. These settings are for local development; production supplies its own environment.
9. **Activity audit.** Server timestamps and authenticated traveler IDs own every event. Frontend
   payloads contain only allowlisted page/control IDs and outcomes; backend auth and passport events
   never copy request bodies. The database is authoritative; JSONL is a private, best-effort mirror.
   `ACTIVITY_LOG_DIR` can override its absolute directory. Anonymous clicks and failed attempts with
   no verified traveler identity cannot be assigned to a traveler.
10. **Predeployment build path.** A GitHub Actions workflow gates backend, frontend, OCR, PostgreSQL
    migration, and image smoke checks. Python runtime/test dependencies are pinned in lock files. Alembic
    owns production schema changes; an exact old local schema can be stamped without data loss.
    The image includes Tesseract, runs as non-root, and checks database/schema/OCR readiness.
    JSON request logs contain a server-generated request ID, route template, status, and duration;
    request bodies and values are omitted. Production hosting, durable private storage, API rewrites, secrets, and release automation
    remain deployment decisions.
11. **Netlify frontend build (now the rollback).** Publishes `frontend/dist`; a generated `_redirects`
    serves SPA paths and proxies API paths to `BACKEND_URL`. Passport review saves owner-scoped fields beside the image.
12. **Free Render demo backend (now the rollback).** `render.yaml` runs migrations at startup; free instances
    lose files and the database expires after 30 days, so passport uploads are disabled there.
13. **Passport review UI (US 6–8).** One page at `/passport/:uploadId`: drag-and-drop or camera upload, then a
    review form where each field shows how far the machine could verify it (check failed / auto-corrected /
    passed check / confirm manually); editing a field marks it "Edited". Only confirmed fields are saved.
    Field rules live in `frontend/src/passport/fields.ts`, separate from the components.
14. **Passport assistant (US 23-lite).** `POST /assistant/messages` makes one Gemini call per question. The
    server, not the browser, adds context: the traveler's latest *confirmed* passport and the current step;
    request bodies forbid extra fields, so a client cannot supply its own "passport". Days until expiry are
    computed in Python and handed to the model. Safety blocks become a polite reply, a 20 s timeout with
    one retry, a per-traveler in-memory rate limit (20 per 10 minutes), and logs never include prompt text.
    Chat history lives only in the page. **Free-tier caveat:** Google may use free-tier prompts (which include
    the confirmed passport fields) to improve its products, with human review, so the free tier is for demos
    with specimen or test data only; real travelers need a paid tier or another provider (a one-function change
    in `gemini_ask`). *Rejected: a framework (LangChain) or tools, which Sprint 1 doesn't need.*
15. **Lambda deployment path.** `backend/Dockerfile.lambda` packages FastAPI and Tesseract with the AWS
    Lambda Web Adapter; `.github/workflows/deploy-backend.yml` publishes the image to ECR and updates an
    image-based Lambda on main backend changes. AWS OIDC, ECR, Lambda, database, and API Gateway setup
    remain external prerequisites (see `docs/AWS_LAMBDA.md`). Passport uploads stay disabled until private
    durable storage and a suitable upload path exist.
16. **Google SSO configuration and linking.** `/auth/config` serves only the public backend client ID.
    Existing password users explicitly connect Google with bearer authentication and current-password
    confirmation. `traveler.sso_email` records the verified provider email; identity still uses Google `sub`.
    Alembic migrates the column without replacing accounts. Local `dev.py run` migrates before startup;
    AWS deployment backs up SQLite privately before migration. Functional changes stay off `main`.
17. **Email OTP recovery.** Ten-minute, five-attempt codes issue five-minute reset grants; reset
    revokes all sessions and cannot enable Google-only passwords. DB-backed limits and metadata-only
    security logs cover authentication. `admin_user_auth` reports both account types privately.
    SES sender/OAuth administration use sharafm032@gmail.com only; owner remains mhs86@mail.aub.edu.
    SES is sandboxed; see `docs/AUTH_OTP_AWS.md` for verified recipients and deployment prerequisites.
18. **Signed-in password change (US 43).** Email/password travelers confirm their current password
    at `POST /auth/change-password`; the new password follows registration rules. The current session
    stays valid while all other sessions are revoked. Google-only accounts cannot change a password.
    The account page shows the form only when `/auth/me` reports `password_enabled`.
19. **Separate traveler profile (US 43).** `travelerprofile` has a traveler-owned primary/foreign key;
    `Traveler.name` remains the display name. `GET /profile` returns null fields before creation;
    `PUT /profile` replaces all fields. Names and past birth dates are validated; country codes are
    1–3 uppercase letters without a backend country list, and `phonenumbers` normalizes E.164 phones.
    The intake chat can import `ProfileFields` from `app.profile`. Confirmed passports follow the same rules (26).
20. **Account page (US 43).** `/account` holds the profile form, sign-in methods and password change; the signed-in welcome view links there. Country names come from the UN M49 table, with ICAO Doc 9303 codes (`D` for Germany, `RKS` for Kosovo, `TWN` for Taiwan). Account-page activity events are not recorded yet because the backend has no account-page identifier.
21. **Session management backend (US 119).** Auth sessions store a short parsed device label and UTC creation/last-active timestamps; old rows remain null. Last-active updates only on refresh. Owner-scoped `/sessions` endpoints list active sessions, revoke one other session, or revoke all others using the password-change revocation helper. Revoked bearer and refresh tokens fail on the next request. The Sessions section on `/account` marks the current device and can end one or all other sessions.
22. **Roles and admin access (US 131).** `traveler.role` (traveler / support / admin) and `traveler.status`
    (active / suspended) are strings with named CHECK constraints and server defaults, so existing accounts
    became active travelers. Every `/admin` route comes from `create_admin_router` in `app/admin_api.py`
    (`app/admin.py` is the read-only reporting command), whose router-level dependency checks the role and
    status of the traveler row loaded for that request; access tokens carry no role, so demotion or
    suspension applies on the next request, and every `/admin` response is `no-store`. Support is refused
    like travelers until a route opts it in with `require_role`. No sign-up path accepts a role: the first
    admin signs up normally and an operator runs `python manage.py set-role`, which records a `role_change`
    event. SQLite migrations run in one explicit transaction, so an interrupted table rebuild rolls back.
    *Rejected: database enum types (PostgreSQL type migrations, nothing on SQLite), a role claim in the JWT
    (stale until expiry), an admin sign-up endpoint or seeded admin password.*
23. **Admin user management (US 133).** `/admin/users` lists, searches and shows accounts (account data and
    counts only, never passport or profile fields); admins suspend, reactivate and change roles there.
    Suspension revokes every session, and sign-in, refresh and the token check all refuse suspended accounts.
    Each change locks both rows in id order, re-checks the acting admin, refuses self-suspension and
    self-role changes, and commits with a `status_change`/`role_change` event on the changed account
    (`admin:<id>:<old>-><new>`). `traveler.created_at` is backfilled from registration events.
    *Rejected: deleting users (Sprint 3) and audit events for reads.*
24. **Guided application chat (US 9).** Schengen short-stay (type C) launches first: one form covers 29 countries.
    A JSON file per destination holds the questions, order, branching (`show_if`), an eligibility gate (`stop_if`)
    and date rules; it is validated when loaded, and the pure engine `applications/flow.py` picks the next question.
    The AI never picks questions; the mid-flow assistant only explains, from answers the server loads. The server
    accepts only the current question or a change to an answered one, saves each answer at once as a copy with its
    source, and re-checks all answers on every read and write. Page `/apply`, API `/applications`.
    *Rejected: LLM-chosen questions (not testable or auditable) and a hard-coded form per country.*
25. **Opening steps and sidebar (US 4, US 12).** Destination, visa and group size are chat steps before the record
    exists (they choose the question file) and are fixed after. Group size is recorded only, until US 81. The
    sidebar names applications by the answers the file's `summary` points at. Signed in, the main button is
    "Start an application".
26. **Pre-fill (US 10).** A question's `prefill` names a source (`passport`, `profile.address`, `profile.phone`).
    The server offers the current question's value from the traveler's own latest confirmed passport or profile,
    only if it passes the question's rules, and recomputes it when the traveler confirms (`use_suggestion`), so
    the browser can't claim a source. Editing changes only the application. Passport reviews are now saved as
    `ConfirmedPassportFields` (profile code and birth-date rules); OCR output keeps the looser `PassportFields`.
27. **Admin dashboard (US 132).** Pages at `/admin` (`frontend/src/admin/`) call the API as `/admin-api/*`, which
    Vite, nginx and Netlify rewrite to `/admin/*`, so page loads never hit the API. The layout asks `/admin/me`
    first: signed-out visitors go to sign-in, everyone else refused goes home with a notice. This only hides pages;
    the backend is the protection. Every action needs a confirmation and ends in a toast.
28. **Applications dashboard (US 19, 20, 79).** Pages `/dashboard` and `/dashboard/:id` (`frontend/src/dashboard/`),
    not `/applications`, which is the API prefix. `application.archived_at` (null = active) hides an application from
    the dashboard and sidebar; `GET /applications?archived=true` lists archived ones; archiving leaves `updated_at`
    alone, and an archived application is read-only (answers get 409, reads store nothing) until restored. Delete is a hard delete of the application and its answers (answers first, for PostgreSQL); passport
    uploads stay. `delete_application` in `applications/lifecycle.py` is there for account deletion to reuse. The
    timeline is derived from stored timestamps (started, each answer's last save, archived), so a changed answer shows
    once; "what happens next" comes from the flow engine, not the AI. *Rejected: an application event table (more
    schema, more to delete) and reusing `ActivityEvent` (no application id, outlives the application).*

## Personal instructions

Personal preferences go in a local, gitignored file, never in this one. Claude Code uses
`CLAUDE.local.md` at the repo root (already in `.gitignore`). Other tools have their own local equivalents.
