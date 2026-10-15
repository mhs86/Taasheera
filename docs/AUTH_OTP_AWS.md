# Google sign-in and email OTP recovery

The feature branch is `mhs86_auth_otp_sprint1`, created from `dev`. Merge functional
changes to `dev` only. `main` must receive configuration/deployment changes only.
Deploy the tested `dev` commit to the existing EC2/CloudFront stack, not Lambda.

## Accounts and administrator reporting

`traveler` is the users table. `auth_type` is `email_password` or `google` and a
DB constraint ties that type to the presence/absence of a password hash. Migration
backfills existing accounts without changing IDs, passwords, Google subjects or
passport ownership. `sso_email` stores the verified Google email separately;
Google authentication always uses its stable verified subject. `last_login_method`
and `last_login_at` record the last successful sign-in. Existing password accounts
may explicitly connect Google after authenticating and confirming their password;
they remain password-enabled and can recover that password with OTP.

The private SQL view `admin_user_auth` lists account type, password/Google login
capabilities and last successful login. It omits password hashes and Google subjects.
It is available to trusted database operators, not exposed as a public admin API.
On the EC2 host through Session Manager:

```bash
sudo docker compose -f /opt/taasheera/deploy/aws/compose.yaml exec -T api \
  python -m app.admin --summary
sudo docker compose -f /opt/taasheera/deploy/aws/compose.yaml exec -T api \
  python -m app.admin --limit 20
```

The reporting command executes a read-only database transaction. A normal app
account does not grant administrator access to other travelers.

## API contract

- `GET /auth/config`: public Google client ID only, no-store.
- `POST /auth/google`, `{id_token}`: verifies signature, issuer, audience, expiry,
  subject and verified email. Creates a Google-only account on first sign-in;
  returns the existing session contract on subsequent sign-ins. It never merges
  an existing password account by matching email.
- `POST /auth/google/link`: existing owner bearer, current password, verified Google
  token and expected owner ID are required. No replacement/unlink shortcut.
- `POST /auth/forgot-password`, `{email}`: identical 202 response for password,
  Google-only, unknown and rate-limited accounts. Only password-enabled accounts
  receive email. No OTP is returned in the response.
- `POST /auth/verify-reset-code`, `{email,code}`: six ASCII digits, 10-minute expiry,
  five attempts per challenge, one successful use. Returns `{reset_token,expires_in}`
  where the high-entropy grant expires in five minutes.
- `POST /auth/reset-password`, `{token,password}`: consumes that grant once,
  changes the existing user's bcrypt hash, revokes all device sessions and all
  outstanding recovery material. Requires a fresh login; it cannot enable a
  password on a Google-only account. Passwords require 8 characters, max 72 UTF-8
  bytes. Prior email-link tokens are invalidated by migration.

The browser shows an OTP form before the new-password form. Recovery secrets stay
in memory, not query strings, local storage or logs. Google is available on both
sign-in and create-account screens. Recovery for Google-only accounts is through
Google. Changing the recovery email is not part of this feature.

## Abuse controls and logs

Admission counters persist in the shared DB, including failed requests and process
restarts. Password login: 30/IP and 10/email per 15 minutes; registration: 10/IP
and 3/email per 15 minutes; Google exchange: 30/IP per 15 minutes; explicit linking:
30/IP and 5/owner per 15 minutes. Recovery requests: 20/IP/hour, 5/email/hour,
1/email/minute, and 100/deployment/hour. Code verification: 60/IP/hour and
10/email/15 minutes, in addition to five guesses/challenge. Completion:
60/IP/hour. Resending invalidates previous codes and grants. Owner-row locking
and atomic token consumption serialize races with login, verification and reset.

Codes are cryptographically random, stored only as nonce-bound HMAC digests using
the private signing secret. Tokens are stored only as SHA-256 hashes. Rate-limit
identifiers use keyed hashes. Security logs contain request ID, operation, outcome
and internal traveler ID only; request logs contain route template/status/duration.
They omit emails, IPs, passwords, codes, tokens and provider errors. Successful
reset audit rows commit with the password/session transaction. CloudWatch log
shipping is not configured; inspect Docker logs privately.

The AWS nginx proxy overwrites `X-Taasheera-Client-IP` with CloudFront's generated
viewer address. Only enable `AUTH_TRUST_CLOUDFRONT_PROXY=true` with this private API
and protected origin. Arbitrary forwarding headers are ignored by default.

## Google and SES configuration

The user supplied this public Google web client:
`1019502864941-452hm5u85t8vcrejuh6aeq43dt85sb9p.apps.googleusercontent.com`.
Google authorized origin: `https://d3vh2ppjrlwxee.cloudfront.net`.
The consent app is Testing, with `sharafm032@gmail.com` listed as a test user.
Other Google testers must be added in Google Auth Platform -> Audience.

Only OAuth administration/testing and SES sending use `sharafm032@gmail.com`.
AWS/GitHub ownership remains `mhs86@mail.aub.edu`; AWS account `632630731308`.
SES sender `sharafm032@gmail.com` is user-confirmed verified in `us-east-1`,
with SES in the sandbox. Only verified recipients (including the sender itself)
can receive real emails until AWS grants production access. Acceptance by SES is
not proof of inbox delivery. There are no embedded SMTP credentials or AWS keys.

Production environment settings: `RESET_MAIL_PROVIDER=ses`,
`SES_FROM_EMAIL=sharafm032@gmail.com`, `SES_REGION=us-east-1`. The official Python
SDK gets temporary credentials from the EC2 instance role. `configure-auth.sh`
adds only `ses:SendEmail` for that sender identity and enables the IMDSv2 response
hop limit needed by Docker. The existing AWS owner must run that script in
CloudShell; it checks account and verified sender before any mutation.

```bash
cd ~/Taasheera-aws
git fetch origin dev
git switch dev
git pull --ff-only
bash deploy/aws/configure-auth.sh
bash deploy/aws/redeploy.sh
```

Configure IAM once, then use only redeploy for subsequent app releases. No new EC2,
EBS or CloudFront resources are created. Bootstrap privately backs up SQLite
before migration and briefly stops the app. Existing JWT/settings/data persist.
Do not redeploy older application code onto the newer database schema.

For manual GitHub Actions deployment, the optional OIDC role template now trusts
only `dev`; install/update it from authenticated CloudShell, set repository variable
`AWS_FULL_DEPLOY_ROLE_ARN`, then run **Deploy dev to existing AWS host**, selecting
`dev`. IAM prerequisites are not assumed to have been applied.

## Review after deployment

Check HTTPS readiness and `/auth/config` for the new public client. Register a
password account using the verified Gmail, request a code, enter it, set a new
password, then confirm old-password and old-session rejection. Google using that
same email will require explicit Connect Google on the password account. To test
Google-only signup independently, use a different Google test account, or test a
Google-only account first; it must not accept password login or send reset OTPs.
Do not delete real users to create a test scenario. Google-only sign-in on the
same Google subject always returns the same traveler row.

Local tests use synthetic Google verification and fake/stubbed email transports;
they do not prove real Google browser login or SES inbox delivery. SES sandbox and
Google Testing restrictions remain visible operational prerequisites.
