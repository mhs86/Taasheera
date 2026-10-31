# Taasheera monitoring runbook

**Admin view:** `/backoffice`, authenticated with an active admin account.
`GET /admin/monitoring` returns actual application counts, latest backend failure
metadata, and pending erasure count. Agent failure ingestion remains pending the
agent workflow; the UI says so explicitly. No document contents are exposed.

**Logs:** backend request/security logs go to stderr (container logs on the existing
host). Requests carry `X-Request-ID`; correlate it with `taasheera.requests` JSON
records containing route template, method, status and duration. Never enable raw
request body, authorization-header, cookie or query-string logging. Activity is
authoritative in `activityevent` in the configured database. Private best-effort
JSONL mirrors live under `$ACTIVITY_LOG_DIR/<traveler_id>/YYYY-MM-DD.jsonl`, default
`backend/storage/activity-logs/`. Passport access records live in `documentaccess`;
travelers see only their own entries at `/account`. Preview logs/files are separate
under `backend/storage/feature-preview/`.

**Sentry:** provision frontend/backend projects and set backend `SENTRY_DSN` and
frontend build-time `VITE_SENTRY_DSN`. No DSN means no reporting. Both SDKs discard
user details, request data, breadcrumbs, exception messages/stacks and form values;
only a generic error plus component and backend request ID are sent. Default
integrations, session replay and tracing are off. Configure issue notifications
to the team's chosen channel in Sentry; no channel or credentials are seeded.
For synthetic local delivery tests, export DSNs and start preview with
`--enable-monitoring`. Trigger the unavailable assistant using specimen data for a
backend 503; a browser `error` event exercises frontend reporting. Confirm the event
contains metadata only. Automated SDK transport tests run offline.

**Uptime:** configure repository variable `UPTIME_URL` to the externally reachable
`/health/ready` URL and secret `UPTIME_ALERT_WEBHOOK` to the team's HTTPS incoming
webhook. `.github/workflows/uptime.yml` checks every five minutes after it reaches
the default branch, or via manual dispatch when available. The job stays disabled
without `UPTIME_URL`. Three probes, each with a ten-second timeout, precede an alert;
the alert contains no URL, credentials or response body. No live alert was sent as
part of local QA. GitHub schedules can be delayed; this is a course-project check,
not a guaranteed paging service. For a local probe:

```bash
UPTIME_URL=http://127.0.0.1:8000/health/ready python backend/scripts/monitor_uptime.py
```

**Incident response:** check readiness, then the latest dashboard error and request
ID. Check database connectivity/current Alembic revision, free disk space, file
permissions, Tesseract and recent releases. Do not change JWT secrets or cookie
security to troubleshoot availability. If erasures are pending, correct storage/DB
access and run `python retry_erasures.py` in the backend container with the existing
database/JWT environment and explicit `PASSPORT_STORAGE_DIR` and `ACTIVITY_LOG_DIR`.
Run this retry on an operator schedule as well as startup; repeated failure exits
nonzero. An account remains suspended until cleanup completes. The local equivalent
is `python preview.py retry-erasures`. All workers sharing local files must share
their activity-parent `.account-locks` directory; a future multi-host/S3 storage
adapter needs distributed locking/erasure coordination before enabling uploads.

**Retention and release:** deletion removes current application DB rows and managed
local owner folders. Historical infrastructure logs and existing private backups
follow the operator's retention policy; no backup rotation is changed by this branch.
Agree retention and erasure/reapplication after a backup restore before production.
Never restore an erased account into active service. Review the separate Google
consent checklist; publishing consent and configuring external monitoring require
the respective owner accounts. Do not deploy or merge before user branch testing.
