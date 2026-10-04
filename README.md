# Taasheera
Visa Application agent and assistant

The React application lives in [`frontend/`](frontend/). To deploy it on Netlify,
follow [`docs/NETLIFY.md`](docs/NETLIFY.md); the repository-root `netlify.toml`
builds and publishes the Vite app. Account and passport features also require the
separately hosted FastAPI service in [`backend/`](backend/).

For a free account-sign-in demo, [deploy the existing API to Render](https://render.com/deploy?repo=https://github.com/mhs86/Taasheera), then set Netlify's `BACKEND_URL` to its HTTPS URL. See the [Netlify deployment guide](docs/NETLIFY.md) for the required steps and free-tier limits.
