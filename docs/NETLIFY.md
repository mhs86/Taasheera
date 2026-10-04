# Deploy the frontend on Netlify

The site is the Vite app in `frontend/`. Its built `dist/index.html` contains the homepage, FAQ, sign-in, registration, password reset, and passport review routes. Do not point Netlify at a new root `public/` directory; that would bypass the application.

## Netlify site settings

1. Connect this Git repository and select the `main` branch for production deploys. If the site is currently linked to a branch containing only a README, change its production branch to `main` in **Project configuration → Build & deploy → Continuous deployment**.
2. Keep the repository-root `netlify.toml`. It sets base directory `frontend`, build command `npm run build:netlify`, publish directory `dist`, and Node 24.14.0. Remove any conflicting UI build or publish settings.
3. Trigger a fresh deploy. The build produces `dist/index.html`, bundled assets, and `dist/_redirects` so direct visits to `/faq`, `/sign-in`, `/reset-password`, and `/passport` load the React router.

The homepage and FAQ work with this alone. Account actions require the existing FastAPI backend at a separate public HTTPS origin. Netlify's static hosting does not run the Python API or Tesseract OCR. If `/auth/register` returns a Netlify 404, the API is not connected.

## Connect the backend

1. For a free account-sign-in demo, use the repository's [Deploy to Render blueprint](https://render.com/deploy?repo=https://github.com/mhs86/Taasheera). It runs the existing `backend/Dockerfile`, creates a free PostgreSQL database, generates a JWT secret, and runs migrations before the API starts. Wait for `/health/ready` on the new `https://...onrender.com` URL to return `{"status":"ok"}`.
2. In Netlify **Project configuration → Environment variables**, set build variable `BACKEND_URL` to that bare HTTPS origin, for example `https://taasheera-api.onrender.com` (no path). Trigger a new deploy. The build writes proxy rules for `/auth/*`, `/passports/*`, and `/activity/*` before the SPA fallback. Browser requests remain on the Netlify origin, so the refresh cookie stays first-party.
3. The blueprint sets `AUTH_ALLOWED_ORIGINS=https://shiny-tartufo-cebfc7.netlify.app`, `AUTH_COOKIE_SECURE=true`, `APP_ENV=production`, and `SCHEMA_AUTO_CREATE=false` for this Netlify site. If the site URL changes, update `AUTH_ALLOWED_ORIGINS` on the backend.
4. For Google sign-in, set Netlify build variable `VITE_GOOGLE_CLIENT_ID` and backend `GOOGLE_CLIENT_ID` to the same Web client ID. Add `https://shiny-tartufo-cebfc7.netlify.app` to that Google client's authorized JavaScript origins. Redeploy after changing the Netlify variable.

Render's free web service sleeps after 15 minutes idle and can take about a minute to wake. The first browser request may fail during that wake-up; wait and retry. Its free PostgreSQL database expires after 30 days and has no backups. Free Render has no persistent filesystem, so the blueprint **disables passport uploads** to avoid losing private images. This path is for testing registration and sign-in with disposable accounts. Deploy durable private file storage and a lasting database before accepting real passports or relying on the service for production.

`VITE_*` values are visible in the built JavaScript. Never put passwords, API keys, database URLs, or JWT secrets in them. Password reset email also needs the backend SMTP settings in `backend/.env.example`.

## Verify the deployed site

Visit `/`, `/faq`, and `/sign-in` directly in a new browser tab. With the backend connected, register with a disposable account, sign in, reload, and sign out. Check that `/auth/refresh` returns a JSON 401 when signed out, not `index.html`. Passport uploads stay unavailable on the free Render blueprint.

Locally, from `frontend/`: `npm ci`, `npm test`, `npm run lint`, `npm run build:netlify`. Set `$env:BACKEND_URL='https://api.example.com'` before the last command to inspect proxy rules. From `backend/`: `.\.venv\Scripts\python.exe -m pytest -q`.
