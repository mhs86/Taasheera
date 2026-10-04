# Deploy the frontend on Netlify

The site is the Vite app in `frontend/`. Its built `dist/index.html` contains the homepage, FAQ, sign-in, registration, password reset, and passport review routes. Do not point Netlify at a new root `public/` directory; that would bypass the application.

## Netlify site settings

1. Connect this Git repository and select the `main` branch for production deploys. If the site is currently linked to a branch containing only a README, change its production branch to `main` in **Project configuration → Build & deploy → Continuous deployment**.
2. Keep the repository-root `netlify.toml`. It sets base directory `frontend`, build command `npm run build:netlify`, publish directory `dist`, and Node 24.14.0. Remove any conflicting UI build or publish settings.
3. Trigger a fresh deploy. The build produces `dist/index.html`, bundled assets, and `dist/_redirects` so direct visits to `/faq`, `/sign-in`, `/reset-password`, and `/passport` load the React router.

The homepage and FAQ work with this alone. Account and passport actions require the FastAPI backend at a separate public HTTPS origin. Netlify's static hosting does not run the Python API or Tesseract OCR.

## Connect the backend

1. Deploy `backend/Dockerfile` on a host that supports containers and a persistent private volume for `PASSPORT_STORAGE_DIR`, plus a managed PostgreSQL database. Follow `docs/DEPLOYMENT_PLAN.md` for migrations and secrets. Do not upload real passports until private durable storage is configured.
2. Set Netlify build environment variable `BACKEND_URL` to the backend's bare HTTPS origin, for example `https://api.example.com` (no path or trailing slash). Redeploy. The build writes proxy rules for `/auth/*`, `/passports/*`, and `/activity/*` before the SPA fallback. Browser requests remain on the Netlify origin, so the refresh cookie stays first-party.
3. Set backend `AUTH_ALLOWED_ORIGINS=https://shiny-tartufo-cebfc7.netlify.app`, `AUTH_COOKIE_SECURE=true`, `APP_ENV=production`, `SCHEMA_AUTO_CREATE=false`, `DATABASE_URL`, and `JWT_SECRET`. Run `python migrate.py upgrade` before starting the API. Check `/health/ready` on the backend host.
4. For Google sign-in, set Netlify build variable `VITE_GOOGLE_CLIENT_ID` and backend `GOOGLE_CLIENT_ID` to the same Web client ID. Add `https://shiny-tartufo-cebfc7.netlify.app` to that Google client's authorized JavaScript origins. Redeploy after changing the Netlify variable.

`VITE_*` values are visible in the built JavaScript. Never put passwords, API keys, database URLs, or JWT secrets in them. Password reset email also needs the backend SMTP settings in `backend/.env.example`.

## Verify the deployed site

Visit `/`, `/faq`, `/sign-in`, and `/passport` directly in a new browser tab. The first three must render, and `/passport` must prompt for sign-in. With the backend connected, register, sign in, upload a specimen passport, review extracted details, save corrections, reload the `/passport/<id>` URL, and sign out. Check that `/auth/refresh` and `/passports` return API responses rather than `index.html`.

Locally, from `frontend/`: `npm ci`, `npm test`, `npm run lint`, `npm run build:netlify`. Set `$env:BACKEND_URL='https://api.example.com'` before the last command to inspect proxy rules. From `backend/`: `.\.venv\Scripts\python.exe -m pytest -q`.
