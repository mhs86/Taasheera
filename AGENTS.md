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

Current sprint: **Sprint 1**. Goal (from Jira): a deployed app where a traveler can find the URL, sign in,
upload a passport, have the details extracted and corrected, and have an onboarding page.
Areas: Al Hariri (auth), Sharafeddin (infra, CI/CD, monitoring, frontend deploy), Salman (frontend
shell, homepage, FAQ, error pages), Zeid (passport upload/extraction/review, minimal assistant).
The product backlog (US 1 to US 130, 15 epics) is a guide and will change. Update this section each sprint.

Git:
- `main` is production. It only receives merges from `dev` once the sprint's work is tested.
- `dev` is the integration branch. Branch off `dev` for each feature and PR back into `dev`.
- Branch naming (existing convention): `<name>_<feature>_sprint<N>`, e.g. `hariri_auth_sprint1`.
  Reference user story numbers (e.g. "US 7") in PR titles/descriptions.
- Keep PRs focused on one feature. Say *why* in the PR description, not just what.
- Never commit secrets, `.env` files, local databases, or real passport images (use specimen
  passports or synthetic MRZ data for tests).

## Tech stack

Status key: **in use** = already in the code · **proposed** = tentative recommendation, adopt or
replace by team agreement and then update this table.

| Area | Choice | Status | Why |
|---|---|---|---|
| Backend | Python, FastAPI, SQLModel, Pydantic v2, uvicorn | in use | Typed validation, auto OpenAPI docs; Python is where the OCR/AI libraries are |
| Auth | bcrypt, PyJWT access tokens in memory, rotating HttpOnly refresh cookies, google-auth | in use | See `backend/app/auth.py`, `google_auth.py` |
| Frontend | React 19, TypeScript, Vite, ESLint | in use | Mainstream, fast dev loop, types catch API mistakes |
| Database | SQLite in local dev; PostgreSQL driver and Alembic migrations | migration code in use; managed PostgreSQL pending | `migrate.py upgrade` versions the current schema; local bootstrap still uses `create_all` |
| File storage | Owner-scoped local folder in dev; private S3-compatible bucket before production | local in use; bucket proposed | Passports must never sit in a public folder or on an ephemeral server disk |
| Passport OCR | Tesseract via pytesseract, MRZ located and repaired by our code (`backend/app/passport/`); vision LLM fallback when check digits fail | in use (vision fallback proposed) | MRZ check digits let us verify a read instead of trusting it |
| LLM | Google Gemini (`gemini-3.5-flash-lite`, free tier) via the official `google-genai` SDK, called only from the backend (`backend/app/assistant.py`); tool use later | in use (assistant); tool use proposed | Free for the course; keys never reach the browser; the provider sits behind one adapter function, so it can change without touching the endpoint |
| Frontend routing, toasts | React Router (data router: routes, 404, error boundaries), sonner (toasts via `src/api.ts`) | in use | Page crashes and failed API calls show a page or a toast instead of a blank screen |
| Frontend styling | Plain CSS with custom properties (`src/index.css` tokens); DM Sans + Space Grotesk, layout modelled on Migraide (simple, no pricing) | in use | Small site, no extra build tooling; auth screens use the same site font and scoped form styles. Tailwind not adopted (see decision 6) |
| Frontend data fetching | TanStack Query (loading/error states) | proposed | Adopt once pages load real data |
| Backend hosting | Non-root container with Tesseract and health checks (`backend/Dockerfile`); free Render demo blueprint (`render.yaml`) | image and blueprint in use; live host pending | Free Render can demo auth; its expiring database and ephemeral files are unsuitable for real passport storage |
| Frontend hosting | Netlify static hosting (`netlify.toml`, see `docs/NETLIFY.md`); Vercel config retained | Netlify build and SPA fallback in use; API proxy needs backend URL | Build `frontend/dist`; proxy `/auth`, `/passports`, and `/activity` through the browser origin so cookies stay first-party |
| Domain | One public frontend origin with an API proxy | proposed | Auth cookies work on the browser origin; production proxy and HTTPS are not configured yet |
| CI/CD, observability | GitHub Actions CI and JSON request logs with request IDs; deployment job, Sentry, uptime check | CI/request logs in use; deployment and monitoring proposed | CI runs tests, lint, build, PostgreSQL migration, and container smoke checks without deployment credentials |
| User activity logging | SQLModel `ActivityEvent` plus private per-traveler JSONL mirrors in `backend/storage/activity-logs/` | in use | Auth and passport actions are recorded on the backend; allowlisted frontend page/control events use authenticated `/activity/events` |
| Later sprints | Playwright (Python) for L2/L3 portal filling; pypdf for L1 PDF forms; a job queue (e.g. arq + Redis) for long agent runs; Telegram Bot API; transactional email | proposed | Not needed in Sprint 1 |

Layout: `backend/app/` (router factories included by `main.py`), `backend/alembic/`
(schema revisions), `backend/scripts/` (passport demo), `backend/tests/`,
`frontend/src/`, `frontend/tests/`. Deployment plan: `docs/DEPLOYMENT_PLAN.md`.

Local Windows setup is in `backend/README.md` and `frontend/README.md`. From `backend/`,
create `.venv`, install `requirements-dev.lock`, run `python dev.py setup` once, then
`python dev.py run` to load the ignored local JWT secret and public Google client ID and
serve on port 8000. From `frontend/`, run `npm ci` and `npm run dev` on port 5173.
Check with backend `python -m pytest -q` and frontend `npm test`, `npm run lint`,
`npm run build`. The authenticated API proxies `/auth`, `/passports`, `/activity`, and `/assistant` through Vite;
the standalone passport demo is separate. OCR needs system Tesseract on `PATH`. The assistant needs `GEMINI_API_KEY` (free from Google AI Studio) in the backend environment; without it `/assistant/messages` returns 503 and everything else works.
Local `dev.py run` still creates missing tables; deployment uses `python migrate.py upgrade`
before starting the API with `APP_ENV=production` and `SCHEMA_AUTO_CREATE=false`.

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
   setting. The frontend reads the same public client ID from `.env.development`. Registration
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
11. **Netlify frontend build.** Build the existing Vite app from `frontend/` and publish `dist/`.
    A generated `_redirects` file serves SPA paths and, when `BACKEND_URL` is set, proxies API
    paths to an HTTPS FastAPI host. Passport review now saves owner-scoped corrected fields beside
    the private image. Netlify only hosts the frontend; backend hosting and durable storage remain required.
12. **Free auth demo backend.** `render.yaml` deploys the existing API and a temporary PostgreSQL
    database on Render. The Render startup command runs Alembic migrations because its free plan
    has no pre-deploy command. Free instances lose local files and the free database expires after
    30 days, so passport uploads are disabled there; durable storage is still needed for production.
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

## Personal instructions

Personal preferences go in a local, gitignored file, never in this one. Claude Code uses
`CLAUDE.local.md` at the repo root (already in `.gitignore`). Other tools have their own local equivalents.
