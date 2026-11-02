# US 1: public app-domain pages

The existing AWS website is `https://d3vh2ppjrlwxee.cloudfront.net`.
The home page was reachable during inspection on 31 October 2026. `/privacy` and
`/terms` rendered the app's 404 page; an HTTP 200 SPA shell was not evidence that a
policy existed. Public, standalone policy documents are now included in the source:

| Google field | Value after the policy publisher succeeds |
|---|---|
| Application home page | `https://d3vh2ppjrlwxee.cloudfront.net/` |
| Application privacy policy link | `https://d3vh2ppjrlwxee.cloudfront.net/privacy.html` |
| Application Terms of Service link | `https://d3vh2ppjrlwxee.cloudfront.net/terms.html` |

The policy files are plain HTML and CSS. They require no login, JavaScript, API
token or cookie. Their actual links are in the homepage HTML shell, outside the
React root, so they remain visible before application startup. The notice covers
Google identity use, passport/application data, hosting, sessions, recovery email,
optional AI processing and the Gemini free-tier disclosure, correction/deletion,
backup/log retention and project contact `sharafm032@gmail.com`.
It describes the course demonstration rather than claiming a legal/compliance
certification, guaranteed retention deadline, visa approval or a production SLA.

## Publishing only the policy pages

The user separately authorized creating and publishing these public pages on AWS.
This does not authorize a full release of the unaccepted Sprint 3 application.
The publisher checks the documented AWS account `632630731308`, reads the existing
`taasheera` stack outputs, and sends a bounded SSM command to that stack's instance.
It creates no AWS resources, changes no DNS/certificate/IAM configuration, and does
not stop/rebuild the app or read/change private environment files, database,
passport storage, JWT secrets or Google client settings.

Only `privacy.html`, `terms.html`, `legal.css` and the homepage's policy links are
updated in the running web container. Existing JS/CSS asset references are retained.
The previous public files are backed up under
`/srv/taasheera/public-policy-backups/`. Copies are installed through atomic renames.
The command checks actual public page content, homepage links and API readiness;
failure attempts to restore all previous public files and remove newly added ones.

From a checkout of this branch in **authenticated AWS CloudShell**:

```bash
python3 deploy/aws/publish_public_policies.py
python3 deploy/aws/publish_public_policies.py --execute
```

The first command is a read-only plan; the second executes the already prepared
publication. It uses the existing AWS CLI identity and preserves runtime credential
configuration. The AWS account email is an identifier, not an API credential.
Missing credentials stop before any AWS changes. No keys should be pasted into chat.

Policy source is included in normal future frontend builds. This targeted publish
also works before that source is merged into the deployed app branch. Until the
reviewed policy source is included in that release branch, rerun this publisher
after any full web-container rebuild, which replaces its served files. No other
Sprint 3 feature needs to be deployed to make these policy pages public.

## Google domain ownership

The user currently has no custom domain. Do not purchase or invent one. The
distribution hostname is distinct from the AWS-owned shared suffix `cloudfront.net`;
do not enter `cloudfront.net` itself as a domain you own.

Google permits verified top private domains in the Authorized domains field.
Try the exact distribution hostname `d3vh2ppjrlwxee.cloudfront.net` if the Console
accepts it, and verify control of that site through Google Search Console. Public
pages alone do not complete this verification or Google brand review. If the Google
Console does not accept this hosted hostname, choose an owned custom domain before
claiming production brand verification. Acceptance has not been tested in an owner
Google session here.

For HTML-tag verification, add the **URL-prefix** property
`https://d3vh2ppjrlwxee.cloudfront.net/` in Search Console, using a Google account
with the required project access. Copy only the `content` value from its public
`google-site-verification` meta tag and publish it with:

```bash
python3 deploy/aws/publish_public_policies.py --execute --google-site-verification PUBLIC_META_TAG_CONTENT
```

Replace the placeholder with the actual public verification value. This is not an
OAuth ID/access token, client secret or password. The publisher adds only its own
verification meta tag and preserves other owners' existing verification tags.
Return to Search Console and click Verify. Then save the accepted authorized
domain and the three public links in Google Auth Platform branding.

Official references:

- [Google app branding and authorized domains](https://support.google.com/cloud/answer/15549049)
- [Google homepage requirements](https://support.google.com/cloud/answer/13807376)
- [Google site ownership verification](https://support.google.com/webmasters/answer/9008080)
- [Public Suffix List](https://github.com/publicsuffix/list/blob/master/public_suffix_list.dat)

## Validation and publication status

Validation covers complete no-script public documents, links without authentication,
mobile layout with JavaScript disabled, unchanged application asset references,
idempotent homepage patches, account checks, read-only planning, bounded SSM payload,
public-file backups and rollback on partial writes or public verification failure.
Existing frontend tests, ESLint and the production build also pass.

At preparation time, this cloud environment had no configured AWS credentials;
the STS check and publisher correctly refused unauthenticated access. The user
then published the prepared assets from authenticated AWS CloudShell on
31 October 2026, using SSM command `f7c5b35e-fc05-4c65-95d8-6ba772c9a06b`.

Independent HTTPS checks confirmed the homepage, `/privacy.html`, `/terms.html`
and `/health/ready` all returned 200, the policy documents contained their actual
headings, the homepage contained both policy links, and API readiness remained
`ok`. The three URL values above are now live. Google Search Console ownership
and Google Auth Platform brand verification are separate, still-pending steps.
