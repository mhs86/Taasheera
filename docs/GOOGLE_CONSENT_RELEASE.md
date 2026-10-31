# CMPS271-141 / US 1: Google consent production handoff

This step is **not completed by local code**. It requires the Google Cloud project
owner, control of a production domain, and a real Google sign-in check. No Google
Cloud owner session or domain-management connection is available to this coding
environment. Existing OAuth client IDs and development origins were preserved.

Use the existing project/client described in [GOOGLE_SSO_AWS.md](GOOGLE_SSO_AWS.md),
with **sharafm032@gmail.com** for OAuth support/developer administration as specified
there. Do not create a second OAuth application or replace the JWT signing secret.

1. In Google Cloud Console, confirm the correct project and Web OAuth client. Keep
   existing local and hosted JavaScript origins. The currently documented hosted
   origin is `https://d3vh2ppjrlwxee.cloudfront.net`; this is a hosting address,
   not evidence that the team owns the registrable `cloudfront.net` domain.
2. Select the team's actual owned production domain. Verify ownership through
   Google's required domain verification process, add it to authorized domains,
   and add the exact HTTPS browser origin to the existing Web client's authorized
   JavaScript origins. This app uses a GIS popup and backend ID-token verification;
   it does not need a new `/auth/google` redirect callback.
3. Under Google Auth Platform branding/audience, provide the real app name,
   approved support/developer contacts, homepage and accessible privacy policy
   (and terms if applicable) on the owned production domain. Confirm those pages
   accurately describe passport processing, retention/deletion and any AI provider.
   Do not invent a production domain or publish placeholder legal/contact details.
4. Keep requested scopes minimal: this app uses identity only (`openid`, email,
   profile); it does not need Drive/Gmail permissions. Resolve any verification
   requirements shown by Google, then change audience publishing from **Testing**
   to **In production** using the owner account. Additional Google review may apply.
5. Verify with a real Google account outside the testing allowlist: sign in, reload,
   sign out, link Google to an existing password account with current-password
   confirmation, and verify cross-account linking is refused. Test Google-only
   deletion with a disposable account, including a mismatched Google identity.
6. Record the verified domain, client ID, publish status/date, and acceptance outcome
   in the release review. Never record ID tokens, cookies, passwords or client secrets.

Backend automated tests verify token issuer, signature, audience, expiry, verified
email and subject ownership using synthetic tokens/claims. Those checks do not
establish that the Google production consent screen has been published.
