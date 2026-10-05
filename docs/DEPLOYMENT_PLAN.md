# Deployment preparation plan

This branch prepares repeatable checks and a deployable backend image. It does not publish the app.

## Code completed now

1. Run backend tests (including synthetic OCR and disposable PostgreSQL migration tests), frontend tests, lint, and build in GitHub Actions on branch pushes and PRs into `dev` or `main`. Build and smoke-test the backend image there too.
2. Build the FastAPI image from `backend/Dockerfile` with Tesseract and a font. The process runs as a non-root user and exposes `/health/live` and `/health/ready`.
3. Version the current SQLModel schema with Alembic. `python migrate.py upgrade` initializes an empty database or stamps an existing, exact local schema without deleting records. A schema mismatch stops startup in deployment mode.
4. Pin backend runtime and test dependencies in `requirements.lock` and `requirements-dev.lock`; the frontend already uses `package-lock.json`.
5. Reject unsafe production startup settings, including local HTTP cookie settings, missing database URL, and non-HTTPS browser origins.
6. Emit JSON request metadata with server-generated request IDs, route templates, status, and duration, without logging URLs, submitted values, or credentials.

## Verification before merging

- Run `python -m pytest -q` from `backend/` and `npm test`, `npm run lint`, `npm run build` from `frontend/`.
- Build the backend image. Run its migration command on a disposable database, start the image, and check both health endpoints and Docker health status. Run the migration and an authenticated request against disposable PostgreSQL too.
- Check the workflow YAML and compare the migrated schema with SQLModel metadata.

## Still needed when a host is chosen

- Provision a managed PostgreSQL database and a private, durable home for passport images and activity JSONL logs. The current file paths require a persistent private volume; a bucket adapter is still proposed.
- Configure TLS, one public frontend origin, and a proxy for `/auth`, `/passports`, `/activity`, and `/assistant` before the SPA fallback. `frontend/vercel.json` cannot contain a real API destination until there is a backend URL.
- Supply deployment secrets and settings: `APP_ENV=production`, `DATABASE_URL`, `JWT_SECRET`, `AUTH_ALLOWED_ORIGINS`, `AUTH_COOKIE_SECURE=true`, `GOOGLE_CLIENT_ID`, and any reset-email settings. `backend/.env.example` lists the keys with empty required values. Never copy a local `.env` file into the image.
- Run `python migrate.py upgrade` once as a release step before starting new API instances. Configure trusted proxy IPs, backups, monitoring, and a deployment job for the selected host. Keep deployment credentials out of PR CI.
- Smoke-test registration, sign-in, passport upload/extraction, activity logging, refresh cookies, and password reset on the HTTPS URL before promoting `dev` to `main`.

## Dependency updates

Run these from `backend/` with Python 3.12 and `pip-tools` installed, then rerun tests and the image build:

```powershell
python -m piptools compile --no-strip-extras --output-file requirements.lock requirements.txt
python -m piptools compile --no-strip-extras --output-file requirements-dev.lock requirements-dev.txt
```

The source requirement ranges are human-edited; the two lock files are committed outputs. CI and the image install the lock files.
