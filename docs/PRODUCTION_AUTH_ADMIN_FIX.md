# Production Google sign-in and admin fixes

The user authorized this production release on 31 October 2026. Source branch:
`mohammad_prod_auth_admin_sprint3`, based on the tested Sprint 3 branch including
the current dev application flow and the public legal pages. No dev/main update
is required to release this exact checkout.

## Changes

- An existing password account choosing Google gets **Connect Google to your
  account**, with its existing Taasheera password required once. Explicit
  **Link Google and sign in** verifies both credentials on the server. Later
  Google sign-ins reuse the same account. Its name, primary email, password,
  role and owned data stay unchanged. Email matching alone never grants access.
- The welcome view includes **Your applications** (`/apply`) and **Staff
  dashboard** (`/backoffice`). Links use the current origin. Staff APIs continue
  to refuse travelers/support even when they visit the dashboard URL directly.
- **Staff dashboard → User management → Add an admin**, or `/admin`, accepts an
  existing account's primary email or linked Google email. **Find account**
  previews the account; a separate button confirms admin access. Both Google and
  password registrations work. Missing accounts must register first. Ambiguous
  matches, stale account IDs, suspended accounts and pending erasures are refused.
  Grants use the existing role locks and audit trail; demotions apply immediately.

The production policies were deployed independently through the public-assets
publisher. Their availability does not identify the running frontend/API revision.
Read-only inspection of the live JS bundle found no `/backoffice`, `/apply`, or
**Staff dashboard** markers. A complete application release supplies those routes.

## Deploy from authenticated AWS CloudShell

If the first release failed with `no active session ... context deadline exceeded`
during image builds (SSM `a45bb7e1-272a-4892-991a-1041fbdd8ef6`), update the
existing clean CloudShell checkout and retry:

```bash
cd ~/Taasheera-prod-fix &&
git pull --ff-only origin mohammad_prod_auth_admin_sprint3 &&
python3 deploy/aws/release_production.py --execute --admin-email sharafm032@gmail.com
```

The recovery builds API and web separately with Compose Bake disabled. Migration
and API share one backend image; startup refuses to rebuild it. A disconnected
build session retries once using cached layers; ordinary dependency/build/resource
failures stop immediately. Private logs are under
`/srv/taasheera/private/build-logs/<commit>/`, with resource counters and the last
build output included on failure. No Docker daemon restart, image/cache pruning,
instance upgrade, secret rewrite or data removal is performed. The failed attempt
stopped before backup/migration/service shutdown. Public readiness, homepage and
both policies were independently HTTP-verified after the reported failure.
Recovery validation: 15 deployment/build tests passed, shell syntax passed, and
the real Docker Compose parser confirmed shared backend tags and unchanged
persistent mounts. This does not establish successful execution on the AWS host.

The coding workspace has no AWS credentials or outbound AWS identity. Production
has **not** been changed by preparing this branch. The operator's authenticated
CloudShell can perform the release:

```bash
cd ~
git clone --depth 1 --single-branch --branch mohammad_prod_auth_admin_sprint3 https://github.com/mhs86/Taasheera.git Taasheera-prod-fix
cd Taasheera-prod-fix
python3 deploy/aws/release_production.py --execute --admin-email sharafm032@gmail.com
```

Without `--execute`, the command only prints a plan. The optional admin email
promotes an **existing** account through the existing operator command after
the release verifies successfully; it does not create an account, link Google,
reset a password or reactivate a suspension. Omit it when no bootstrap is needed.
Only the documented AWS account (632630731308) and the stack's existing host are
used. No additional paid resources or IAM/OIDC trust changes are created.

The launcher records the exact checked-out Git commit, calls the existing SSM
deployment with `TAASHEERA_PRESERVE_CONFIG=1`, keeps app.env/web.env byte-for-byte,
builds API/frontend sequentially and makes a private SQLite backup before
migrations. Persistent uploads, data and secrets stay on the existing EBS disk.
Missing existing private configuration causes a failure rather than regeneration.
There is a short service interruption for backup/migration/startup. The existing
deployment does not automatically restore the database on a failed migration;
use the private pre-migration backup and the operational runbook if recovery is
needed, without overwriting any later writes.

The release checks readiness, required frontend feature markers, public policies,
the new linking API's input validation, and anonymous refusals for both admin
endpoints. It reports success only when all checks pass. It never logs private
configuration or credentials. SSM command IDs identify host-side failures; inspect
their logs privately. Do not rerun a still-running release.

## Acceptance checks after release

If a signed-in designated admin sees "An active admin account is required", run
the role assignment independently from the build/release, in AWS CloudShell:

```bash
cd ~/Taasheera-prod-fix &&
git pull --ff-only origin mohammad_prod_auth_admin_sprint3 &&
python3 deploy/aws/release_production.py --admin-only --execute --admin-email sharafm032@gmail.com
```

This calls the operator role command inside the running API container and then
reads the account back to verify `role=admin, status=active`. It does not rebuild,
restart, deploy, change a password, create an account or reactivate a suspension.
The same existing session gains access on the next request; refresh `/backoffice`.
The full release only assigns the designated admin after its public verification
completes, so an interrupted release may leave the application updated while the
role assignment remains pending. Google linking preserves roles and never grants
admin access by email alone.
Role-only recovery validation: 101 operator, release and admin API tests passed,
including real SQLite promotion of both Google and password accounts and reuse of
the same authenticated session. An SSM success without verified active admin
metadata is treated as a failure.

1. Hard-refresh `/sign-in`, choose Google as `sharafm032@gmail.com`, and confirm
   the existing Taasheera password at the new prompt. If forgotten, cancel and
   use password recovery first. Google linking preserves admin access; it does
   not grant it. The operator promotion above configures the designated account.
2. Sign out and sign in with Google again: no linking prompt. Password sign-in
   also still works. Refreshing the page restores the session.
3. Confirm both welcome links point to the production origin. Open `/apply`.
4. Open **Staff dashboard → User management**, enter a synthetic existing user's
   email in **Add an admin**, find the account and explicitly confirm the grant.
   Verify that account can use staff pages. Repeat with a Google-created account.
5. A traveler must still be refused by staff APIs. Check `/privacy.html` and
   `/terms.html` without signing in.

## Automated verification

Local QA on 31 October 2026: **690 backend tests passed** with real SQLite and
PostgreSQL 17 (no skips); **165 frontend tests passed**; **7 Chromium browser
tests passed**. Frontend lint and the production TypeScript/Vite build passed.
Shell syntax and release configuration-preservation tests passed. These results
validate the prepared source, not an already-completed production deployment.

Tests cover Google signature/issuer/audience/expiry/email verification, matching
Google identity plus password, collision preservation, password throttling shared
with ordinary login, no identity writes for suspension or conflicting owners,
both admin account types, exact confirmation, origin checks and role authorization.
The DOM suite exercises linking on sign-in and registration, wrong-password retry,
credential cancellation, account preview and grant. Chromium checks promotion
across two real sessions and mobile layout. Existing application, privacy, erasure,
token/session and migration regressions also run. Provider calls use synthetic
Google credentials; real Google-account acceptance remains an operator check.

Run the existing commands in AGENTS.md. Release-specific backend tests are
`tests/test_google_link_login.py`, `tests/test_production_release.py`, and the
additions in `test_admin_users.py` and `test_postgres_deployment.py`.
