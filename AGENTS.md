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
| Database | SQLite in local dev; PostgreSQL and Alembic migrations | SQLite in use; production setup proposed | `create_all` makes new tables but cannot evolve a shared schema |
| File storage | Owner-scoped local folder in dev; private S3-compatible bucket before production | local in use; bucket proposed | Passports must never sit in a public folder or on an ephemeral server disk |
| Passport OCR | Tesseract via pytesseract, MRZ located and repaired by our code (`backend/app/passport/`); vision LLM fallback when check digits fail | in use (vision fallback proposed) | MRZ check digits let us verify a read instead of trusting it |
| LLM | Anthropic Claude via the official Python SDK, called only from the backend; native tool use for agent features | proposed | Keys never reach the browser; plain SDK over a framework (e.g. LangChain) keeps the agent loop small and debuggable |
| Frontend routing, toasts | React Router (data router: routes, 404, error boundaries), sonner (toasts via `src/api.ts`) | in use | Page crashes and failed API calls show a page or a toast instead of a blank screen |
| Frontend styling | Plain CSS with custom properties (`src/index.css` tokens); DM Sans + Space Grotesk, layout modelled on Migraide (simple, no pricing) | in use | Small site, no extra build tooling; auth screens use the same site font and scoped form styles. Tailwind not adopted (see decision 6) |
| Frontend data fetching | TanStack Query (loading/error states) | proposed | Adopt once pages load real data |
| Backend hosting | Container with Tesseract | proposed | OCR needs a system Tesseract installation; no production image is in this branch |
| Frontend hosting | Vercel static hosting (`frontend/vercel.json`, see `frontend/DEPLOY.md`) | SPA fallback configured; API proxy pending | Proxy `/auth` and `/passports` through the browser origin before deployment so cookies stay first-party |
| Domain | One public frontend origin with an API proxy | proposed | Auth cookies work on the browser origin; production proxy and HTTPS are not configured yet |
| CI/CD, observability | GitHub Actions; JSON logging with request IDs; Sentry; uptime check | proposed | Sprint 1 infra stories |
| Later sprints | Playwright (Python) for L2/L3 portal filling; pypdf for L1 PDF forms; a job queue (e.g. arq + Redis) for long agent runs; Telegram Bot API; transactional email | proposed | Not needed in Sprint 1 |

Layout: `backend/app/` (router factories included by `main.py`), `backend/scripts/`
(passport demo), `backend/tests/`, `frontend/src/`, `frontend/tests/`.

Local Windows setup is in `backend/README.md` and `frontend/README.md`. From `backend/`,
create `.venv`, install `requirements-dev.txt`, run `python dev.py setup` once, then
`python dev.py run` to load the ignored local JWT secret and public Google client ID and
serve on port 8000. From `frontend/`, run `npm ci` and `npm run dev` on port 5173.
Check with backend `python -m pytest -q` and frontend `npm test`, `npm run lint`,
`npm run build`. The authenticated API proxies `/auth` and `/passports` through Vite;
the standalone passport demo is separate. OCR needs system Tesseract on `PATH`.

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

## Personal instructions

Personal preferences go in a local, gitignored file, never in this one. Claude Code uses
`CLAUDE.local.md` at the repo root (already in `.gitignore`). Other tools have their own local equivalents.
