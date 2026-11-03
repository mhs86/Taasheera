# Google SSO on the deployed AWS app

Owner email: **mhs86@mail.aub.edu**. Google OAuth and SES sender administration use
**sharafm032@gmail.com** for this feature only. The Google web client is
`1019502864941-452hm5u85t8vcrejuh6aeq43dt85sb9p.apps.googleusercontent.com`.
This is a public client ID, not a client secret. This GIS popup flow needs no
Google client secret or service-account key.

## Google-side requirement

In Google Cloud Console / Google Auth Platform, edit that **Web application**
OAuth client and add the exact authorized JavaScript origin:

```text
https://d3vh2ppjrlwxee.cloudfront.net
```

Keep existing development origins. Do not append `/sign-in`, `/auth/google`,
a query, or a trailing path. Google completes the popup and the browser POSTs
its ID token to the API; this is not a redirect/form-post OAuth callback, so it
does not require adding `/auth/google` as a redirect URI.
Use **sharafm032@gmail.com** for Google account/support/developer email settings where
required. If the project's audience is in Testing, add that account as a test
user; allow other intended users or publish the consent configuration as
appropriate. AWS cannot change Google's origin allowlist. The project owner
must save it in Google Console, then perform a real browser sign-in.

## AWS configuration and feature deployment

Google SSO is included in the OTP feature targeting `dev`. See
[authentication rollout](AUTH_OTP_AWS.md) for the current configuration and deployment
commands. Functional source must not be pushed to `main`.

The public ID override updates only that setting in the private AWS-host
configuration, preserving JWT and any configured provider/SMTP keys. The frontend
requests `/auth/config` and uses the same ID that the backend verifies. Setting
a different public client ID uses the same command; authorize its origin in
Google first. This deployment reuses existing AWS resources.

The deployment briefly stops API/web containers, makes a SQLite online backup
under `/srv/taasheera/private/backups/`, and upgrades the schema before starting
the new API. The backup remains private on encrypted EBS and contains sensitive
application data. Manage retained backups deliberately; they use disk space.
The daily off-host backup and restore are described in `docs/BACKUPS.md`.
Never run an older application/schema deployment against this database without
a reviewed rollback procedure. Do not redeploy the old `main` application onto
the migrated database: functional changes remain off `main` under the user's rule.

## What changes

The existing `traveler` table receives nullable `sso_email`; no new parallel users
table is created. Existing password users keep their contact email, ID, password
hash and sessions. Existing Google identities receive their historical verified
registration email; a later verified Google sign-in updates it if the provider
email has changed. Authentication and identity uniqueness use the stable Google
subject, not the SSO email.

Signed-out users use the Google popup to create or access a Google-linked account.
Existing password users first sign in, confirm their application password under
**Connect Google**, and choose their Google account. A subject already connected
to another traveler cannot be stolen or silently moved. Primary contact email
can differ from the verified SSO email. No automatic merging happens when emails
match, and users cannot supply their own SSO email to the API.

## Verification

Backend tests cover runtime configuration, linking ownership/password/Google
verification, identity collisions, returning-email changes, and migrations.
Frontend tests cover runtime ID loading, retries, popup callback/link requests,
duplicate callbacks, password cleanup and stale responses. Local production
container checks exercise the actual migration, private database backup,
public configuration endpoint and existing authentication/passport persistence.
Real Google popup success still requires the Google Console change and a browser
session; automated tests use synthetic verified claims and do not authenticate
with a real Google account.

After deployment, open the site in a browser. For a password account, connect
Google explicitly, log out, choose that Google account and confirm the same
traveler's profile and passport data. Reload and log out again to check session
restoration and revocation. Never paste Google tokens, passwords or keys into chat.
