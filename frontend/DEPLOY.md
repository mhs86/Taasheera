# Deploying the frontend

The frontend is a static Vite build (`npm run build` → `dist/`). `vercel.json` configures Vercel;
any static host works if it follows the same rules below.

## Host settings

| Setting | Value |
|---|---|
| Root directory | `frontend` |
| Build command | `npm run build` |
| Output directory | `dist` |
| Node | 22.22.2+ or 24.15+ (same as `npm test`) |

## Routing rules

1. **SPA fallback.** Every path that isn't a built file serves `index.html`, so `/faq`,
   `/sign-in`, `/reset-password` and unknown paths load the app. The app itself shows the 404 page for
   unknown routes. `vercel.json` already does this.
2. **API proxy (add once the backend has a URL).** The browser calls the API on the frontend's
   own origin (`/auth/...` and `/passports/...`), so auth cookies stay first-party. Add rewrites for
   both backend route prefixes **above** the SPA fallback in `vercel.json`, for example:

   ```json
   { "source": "/auth/:path*", "destination": "https://<backend-host>/auth/:path*" }
   { "source": "/passports/:path*", "destination": "https://<backend-host>/passports/:path*" }
   ```

   The backend must then use secure cookies (`AUTH_COOKIE_SECURE=true`) and list the frontend's
   HTTPS origin in `AUTH_ALLOWED_ORIGINS`.

## Environment variables

Vite inlines `VITE_*` variables at build time. They are public, so never put secrets in them.
Set them in the host's project settings, then redeploy.

| Variable | Needed for | Notes |
|---|---|---|
| `VITE_GOOGLE_CLIENT_ID` | Google sign-in | Same Web client ID as the backend's `GOOGLE_CLIENT_ID`. Add the production origin to the client's authorized JavaScript origins. |

## Smoke test on the production URL

1. `/` loads the homepage over HTTPS, with fonts and flags and no console errors.
2. `/faq` loads directly (not only through a link) and shows 10 questions that open and close.
3. `/does-not-exist` shows the 404 page with the site header, not the host's own 404.
4. **Get started** and **Sign in** open the sign-in screens.
5. With the backend stopped or blocked in developer tools, an action that calls the API shows a
   red toast instead of a blank screen.
6. At a 390px-wide viewport, nothing scrolls horizontally and the header buttons fit.
