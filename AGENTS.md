# Ta'asheera (تأشيرة): shared project context

Coding agents read this at the start of every session. Shared facts belong here; personal preferences
belong in the gitignored `CLAUDE.local.md` or an equivalent local file.

## Keeping this file current

- Update affected stack, layout, commands, workflow, conventions and decisions in the same branch/PR.
- Fix stale facts or tell the user when uncertain. Mark adopted proposals and record the decision.
- Keep this concise (under about 200 lines); remove obsolete details instead of accumulating them.

## Product

Group 7's university Software Engineering project is a web AI visa application agent inspired by
Veeza AI. The traveler signs in, chooses a destination/visa/nationality, confirms extracted passport
fields, answers a guided intake, uploads supporting documents, checks consistency, reviews the
cover letter/form, pays and explicitly confirms. Later submission levels: L1 official PDF packet;
L2 portal to review; L3 traveler handles CAPTCHA; L4 manual guide. Status tracking follows submission.

- Passport/document data is private; every data/file request checks the authenticated owner.
- Nothing is submitted without the traveler's explicit confirmation.
- Traveler-facing AI output carries a "not legal or immigration advice" notice.
- Gemini's free tier is for synthetic/specimen demos only: Google may use prompts for improvement
  and human review. Real traveler data requires a paid tier or another provider.

## Sprint 3 and workflow

Sprint 3: **October 20–November 3, 2026**. Goal: working sign-in/recovery, an assistant with full
application context and confirmed actions, persistent conversations, an applications dashboard,
admin monitoring/deletion, and tested work on `main` reaching the live site.

| Member | Owns this sprint | Tested/reviewed by |
|---|---|---|
| Ahmad Zeid | Assistant/context/tools/history, applications engine/router, layout assistant, deployment pipeline (CMPS271-48/87/88/90/93/190) | Dani Salman |
| Ahmad Al Hariri | Auth, Google/reset/OTP, sessions, idle guard, shared rate limiting (CMPS271-5/8/116/119) | Ahmad Zeid |
| Mohammad Sharafeddin | Admin pages/API, logging, document audit, account erasure, monitoring, Google consent (CMPS271-117/120/126/141/157–159) | Ahmad Al Hariri |
| Dani Salman | Applications dashboard/lifecycle, backups, critical-path tests, CI/protection (CMPS271-76/78/82/132/133/155) | Mohammad Sharafeddin |

New features go in new modules; keep edits to another member's files small and coordinate interfaces.
The backlog and plan are guides, not permanent assignments. Update this section each sprint.

- `main` is production; tested sprint work integrates on `dev` before release to `main`.
- Feature branches start from `dev` and PR back to `dev`. Existing names use
  `<name>_<feature>_sprint<N>` (for example `zeid_chat_history_sprint3`).
- Keep PRs focused, reference ticket/story numbers and explain why. Set the rotation's reviewer.
- Never commit secrets, `.env` files, local databases or real passport images; use synthetic data.
- **Alembic has one head.** Before merge, point a new migration at the current `dev` head.
- End other sessions through `revoke_other_sessions` in `backend/app/auth.py`. The suspended-user
  check belongs in the single current-traveler loader, not duplicate endpoint checks.
- Pending Sprint 3 work is tested together on `zeid_sprint3_integration`; merging branches there
  does not merge their PRs to `dev`. Its migration order is privacy → archive → chat history.

## Stack and layout

| Area | In use | Proposed / operational notes |
|---|---|---|
| Backend | Python, FastAPI router factories, SQLModel, Pydantic v2, uvicorn | Environment validated at startup in `app/config.py` |
| Auth | bcrypt, PyJWT access tokens in memory, rotating HttpOnly refresh cookies, google-auth | Roles/status read from the traveler row on every request |
| Database | SQLite on encrypted persistent AWS EBS; Alembic; psycopg driver | PostgreSQL tests need a disposable database; only tests use `create_all` |
| Files | Private owner-scoped local/EBS folders | Private S3-compatible passport storage proposed; never public/ephemeral |
| OCR | Tesseract/pytesseract plus our MRZ locator and checksum repair | Vision-model fallback proposed |
| Assistant | Backend-only official `google-genai` SDK, `gemini-3.5-flash-lite`, function calling | Provider behind adapters; no keys in browser |
| Frontend | React 19, TypeScript, Vite, React Router data router, sonner | TanStack Query proposed |
| Styling | Plain CSS/custom properties in `src/index.css`, DM Sans + Space Grotesk | No Tailwind; auth styles are scoped |
| Hosting | EC2 in `us-east-1`, Docker Compose API + nginx, CloudFront HTTPS | Live: https://d3vh2ppjrlwxee.cloudfront.net; custom domain not configured |
| CI/deploy | GitHub Actions tests/builds, OIDC/ECR deploy-from-main workflow | AWS/GitHub setup required; immutable API/web images are pulled by digest; Render/Netlify/Lambda are alternatives |
| Audit/monitoring | `ActivityEvent`, private JSONL, document access log; Sentry/uptime tooling | Sentry/uptime opt in; metadata allowlists omit private data |
| Backups | Nightly systemd/S3 backup and restore tooling | Provision private bucket/host permissions; see `docs/BACKUPS.md` |

Layout: `backend/app/` (`applications/` pure engine/router and destination JSON questionnaires),
`backend/alembic/`, `backend/tests/`, `backend/scripts/`, `backend/manage.py`, `backend/preview.py`,
`backend/retry_erasures.py`, `frontend/src/`, `frontend/tests/`, `frontend/e2e/`, `deploy/aws/`, `docs/`.

## Local commands and routing

From `backend/`: create `.venv`, install `requirements-dev.lock`, run `python dev.py setup` once,
then `python dev.py run` (migrates before API on port 8000). From `frontend/`: `npm ci`, `npm run dev`
(port 5173). Use **http://127.0.0.1:5173**; local auth rejects an unconfigured `localhost` origin.
Windows instructions: the backend/frontend READMEs. OCR requires Tesseract on `PATH`.

Assistant key: a `GEMINI_API_KEY` line in ignored `backend/.env.local` for `dev.py run`; deployments
supply environment secrets (Render names the key with `sync: false`). **Never commit it: this repo is
public.** Without a key, `/assistant/messages` returns 503 and other features remain available.

Checks: backend `python -m pytest -q`; frontend `npm test`, `npm run lint`, `npm run build`,
`npm run test:e2e` (install Playwright Chromium; set `TAASHEERA_TEST_PYTHON` if needed).
`TEST_POSTGRES_URL` must name a disposable database with create/drop privileges. Browser tests use
ports 8100/5273 and isolated synthetic storage. Preview: `python preview.py run --seed-demo`;
this does not load `.env.local`, sends no mail/Gemini calls, and keeps separate data under ignored
`backend/storage/`. See `docs/LOCAL_FEATURE_TESTING.md`. Avoid `--free-ports` unless stopping the
processes on those ports is intended.

API prefixes `/auth`, `/passports`, `/profile`, `/sessions`, `/activity`, `/assistant`, `/applications`
and `/admin-api` proxy through Vite/nginx/Netlify; `/admin-api` rewrites to backend `/admin`.
A new prefix must be added to `vite.config.ts`, `write-netlify-redirects.mjs`, `deploy/aws/nginx.conf`
and must not collide with page paths. Pages include `/apply`, `/dashboard`, `/dashboard/:id`,
`/passport/:uploadId`, `/account`, `/admin` and `/backoffice`.
Deployments run `python migrate.py upgrade`, `APP_ENV=production`, `SCHEMA_AUTO_CREATE=false`.
Operator role assignment: `python manage.py set-role --email <email> --role admin`.

## Conventions

- Match surrounding code; new backend features use router factories.
- Validate request bodies with Pydantic `extra="forbid"`; validate configuration at startup.
- Never log prompts, document fields, credentials or sensitive error input. Main strips values from 422s.
- Keep owner checks on every data/file route. Use established helpers/libraries over duplicate code.
- Feature changes include meaningful tests; lint, tests and build pass before a PR merges.

## Decisions log

1. **FastAPI/Python.** One language for backend/OCR/AI; rejected a separate Node backend.
2. **React/Vite/TypeScript.** Typed mainstream frontend with a fast local loop.
3. **MRZ-first extraction.** Whole-page Tesseract locates MRZ lines after PassportEye failed on a patterned
   passport. Position repairs and a unique single checksum-passing swap are allowed; retry rotations/scales
   within 6 seconds. Verified/needs_review/unreadable are normal outcomes; traveler confirms every field.
4. **Private uploads.** Re-encode JPEG, apply orientation, strip metadata, random IDs under traveler folders.
5. **Path routing.** Real paths/404/error boundaries; same-origin API proxy keeps cookies first-party.
6. **Plain CSS and sonner.** Tokens in `index.css`; rejected Tailwind's extra tooling/class-heavy markup.
7. **Shared authentication.** Passport endpoints use the same authenticated-traveler dependency as `/auth/me`.
8. **Local auth setup.** Ignored persistent JWT secret; public client ID from `/auth/config`; local HTTP only.
9. **Activity audit.** Authenticated owner and server time; frontend sends allowlisted IDs only. Database is
   authoritative; private JSONL is a best-effort mirror. `ACTIVITY_LOG_DIR` overrides its directory.
10. **Production schema/builds.** Alembic owns migrations, old exact local schemas can be safely adopted;
    pinned dependencies, non-root images, readiness checks and metadata-only JSON request logs.
11. **Netlify rollback.** Generated redirects proxy API paths and serve SPA paths; confirmed passport sidecars.
12. **Render rollback.** Uploads disabled on its ephemeral free tier; database expiry makes it demo-only.
13. **Passport review (US 6–8).** Field verification labels plus human confirmation; rules in `passport/fields.ts`.
14. **Assistant adapter.** One backend provider call per question, deterministic date arithmetic, 20-second
    timeout/one retry, polite safety refusal. Current history and rate-limit behavior supersede the old in-memory demo.
15. **Lambda alternative.** Web Adapter + Tesseract image; OIDC/ECR/Lambda prerequisites documented in
    `docs/AWS_LAMBDA.md`. Uploads disabled without suitable durable storage/upload handling.
16. **Google linking.** Verified `sub` is identity; password accounts explicitly link with password confirmation.
17. **OTP recovery.** Ten-minute/five-attempt codes issue five-minute single-use reset grants; reset revokes
    sessions and cannot enable Google-only passwords. SES sandbox/owner setup: `docs/AUTH_OTP_AWS.md`.
18. **Password change (US 43).** Current password required; current session stays and all others are revoked.
19. **Traveler profile.** Separate owned row; `PUT` replaces fields, validates dates/codes/names and E.164 phone.
20. **Account page.** Profile, sign-in methods, password and sessions; country options use UN M49/ICAO codes.
21. **Sessions (US 119).** Owner-scoped list/revocation; device label and UTC timestamps; shared revocation helper.
22. **Roles (US 131).** Traveler/support/admin, active/suspended with CHECK constraints; no JWT role claims,
    seeded admin password or role sign-up input. Single loader enforces status; admin responses are `no-store`.
23. **Admin users (US 133).** Account data/counts only; ordered locks, actor recheck, no self-role/suspension;
    suspension revokes sessions, changes record audit events. No passport/profile fields in admin listings.
24. **Guided intake (US 9).** Pure deterministic engine, validated per-destination JSON, branching/date rules;
    server enforces order/reconciles every read/write. Answers are copies with provenance; AI never picks questions.
25. **Opening steps (US 4/12).** Destination/visa/group choose the questionnaire before creation and stay fixed.
26. **Pre-fill (US 10).** Server recomputes suggestions from the owner's confirmed passport/profile; strict
    confirmed fields are separate from loose OCR output. Editing an application never rewrites source data.
27. **Completeness (US 13).** Pure check after reconciliation; missing/eligibility stops block, source mismatches
    warn. Owner-scoped `/applications/{id}/check`; same report reaches the assistant. Fix links are later work.
28. **Assistant actions (US 47/110).** Server loads answers/current step/reachable IDs/check report. Gemini
    proposes change/go-to/check; engine validates, traveler confirms, normal answer endpoint validates again.
    No submit tool; multi-field answers stay in the form. Archived applications permit checks but no changes.
29. **Chat history (US 111).** Successful question/reply saved atomically per owner/application (null outside one).
    Owner-scoped GET/DELETE `/assistant/history`; server supplies model history and ignores browser history.
    Account erasure removes all its chats before parent rows; application deletion removes only its own chats.
30. **Assistant anywhere (US 23).** Signed-in site, welcome/account and admin shells mount `GlobalAssistant`;
    passport/apply keep their own. Outside history reloads on first open; `general` has passport context only.
31. **Admin dashboard (US 132).** `/admin` pages call `/admin-api`; backend role/status checks protect data.
32. **Retryable account erasure.** Suspend/revoke/persist intent first, then remove files/rows: 204 complete,
    202 pending. Portable owner file locks serialize deletion with requests. Startup/retry command finish cleanup.
33. **Document audit/monitoring.** Storage hooks record content access before returning data; strict Sentry
    metadata allowlists and opt-in uptime checks. See `docs/MONITORING_RUNBOOK.md`.
34. **Public Google consent pages.** Standalone `/privacy.html`/`terms.html`, linked before JS startup;
    scoped publication tooling and rollback in `docs/GOOGLE_APP_DOMAIN.md`.
35. **Admin by email.** Lookup grants nothing; explicit promotion rechecks identity/status/locks. No allowlist
    or unverified invitations. Existing production release tooling preserves private config and backs up SQLite.
36. **Sequential host builds.** API then web, `COMPOSE_BAKE=false`; retry disconnected sessions once.
    Logs private, no Docker shutdown/prune recovery, startup uses `--no-build`.
37. **Application lifecycle (US 19/20/79).** Archive hides active lists and makes answers read-only until
    restored. Delete removes answers/chat, preserving passport uploads. Timeline derives from saved timestamps.
38. **Backups (US 126).** Online SQLite backup plus passports/activity logs (no private secrets), checksummed
    archive to private/versioned S3. Restore verifies first and preserves replaced data; `docs/BACKUPS.md`.
39. **Main release images (CMPS271-190).** Only current main with successful push CI can release, including
    manual runs. Actions publishes immutable SHA-tagged API/web images to private EC2-specific ECR repos;
    the host pulls digests, verifies revision labels, preserves secrets, backs up SQLite and migrates. Old
    manual dev/bootstrap still builds locally. Owner setup: `deploy/aws/README.md`; no stored AWS keys.
