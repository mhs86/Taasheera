# Taasheera on AWS

Owner/account email: **mhs86@mail.aub.edu**. Expected AWS account:
`632630731308`, region `us-east-1`. All changes in this directory and the
associated workflow are deployment configuration. Application source is unchanged.
Only configuration, infrastructure, CI/CD, and deployment files may be pushed to
`main`; functional changes belong on a feature branch and go through `dev`.

## What this deploys

A single EC2 host runs the existing FastAPI image, Tesseract, and an Nginx image
containing the Vite build. CloudFront provides a free AWS hostname and viewer
HTTPS, forwards cookies and authorization headers, and disables caching.
SQLite and private passport images are on a separate encrypted EBS volume;
the API's port is private. Administration uses Systems Manager, without SSH.
The origin accepts CloudFront addresses and requires a private origin header.
Traffic between CloudFront and EC2 uses HTTP; viewer traffic uses HTTPS.
This is a course/demo deployment, with one host and no automatic backups or HA.
Use specimen data. If stronger transport protection or availability is required,
plan those infrastructure changes before collecting real traveler documents.

The Lambda workflow remains separate. This deployment supports uploads without
changing application storage code or using Lambda's temporary filesystem.

## Cost boundary

This is **not permanently free hosting**. AWS's current Free account plan ends
after six months or when credits run out. The supplied $100 credit balance must
be checked in Billing, including expiry and eligible services, before creating
resources. EC2, encrypted gp3 EBS, one Elastic IP/public IPv4 address, CloudFront
requests/transfer, and any snapshots can consume credits or incur charges on
a Paid plan. There is no NAT Gateway, load balancer, RDS instance, purchased
domain, or container registry. CPU credits are standard, avoiding surplus-credit
charges. The 8 GiB root plus 8 GiB data disks are intentional; Docker builds on a
1 GiB host may need a larger instance and its associated cost.

Set an AWS Billing budget with notifications to **mhs86@mail.aub.edu** and
monitor credit expiry. Budget notifications do not enforce a spending cap.
Do not upgrade to a Paid plan or add paid-only services to make this work without
checking the user's $0 requirement. See [AWS Free Tier](https://aws.amazon.com/free/)
and [account-plan documentation](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/free-tier.html).

## Initial deployment in AWS CloudShell

These are real AWS operations, not validated against an account until credentials
are available. Use the AWS account registered with **mhs86@mail.aub.edu**; do not
create another account. First publish/merge these configuration files so the
host can fetch the exact Git commit. A clean Git checkout is required.

```bash
git clone https://github.com/mhs86/Taasheera.git
cd Taasheera
export AWS_REGION=us-east-1
export AWS_FREE_ELIGIBILITY_CONFIRMED=yes
bash deploy/aws/deploy.sh
```

The first run prepares a CloudFormation change set without executing it.
The scripts disable AWS CLI paging and interactive prompts. If an older script
shows a `:` or `(END)` after the change list, press `q` to close the pager and let
that deployment continue; do not restart it while the stack is being created.
Review it in CloudFormation, then either execute that change set there and rerun
the script, or run:

```bash
export TAASHEERA_EXECUTE_CHANGE_SET=yes
bash deploy/aws/deploy.sh
```

The default VPC must have DNS hostnames enabled; the selected subnet must have
an Internet Gateway route. Set `TAASHEERA_VPC_ID` and `TAASHEERA_SUBNET_ID` if the
account has no suitable default network. Keep `.aws-deploy-state/` private: it
contains the origin token and SSM parameters, never Git credentials.
Read IAM and EC2 errors before retrying. The CloudFront origin prefix list counts
as 55 security-group rules, so its quota must accommodate it.

The script mounts only the stack's data volume, builds images sequentially,
migrates the database before starting the API, and checks the public readiness
URL. JWT signing material is generated privately on the data volume and retained
across redeployments. No secret is committed or printed.
Setup reports its current step. On failure the scripts retrieve the SSM exit
code and error output, excluding the private command parameters.

## Manual GitHub Actions redeployment

After initial deployment, create the OIDC role from CloudShell:

```bash
aws cloudformation deploy --stack-name taasheera-github-role \
  --template-file deploy/aws/github-role.yaml --capabilities CAPABILITY_IAM
aws cloudformation describe-stacks --stack-name taasheera-github-role \
  --query 'Stacks[0].Outputs' --output table
```

If the GitHub OIDC provider already exists, pass
`--parameter-overrides CreateOidcProvider=false`.
Set repository variable `AWS_FULL_DEPLOY_ROLE_ARN` to the resulting role ARN
(an ARN is not a credential). The role trusts only this repository's `main`
branch and allows redeployment only to the tagged stack host. Run **Deploy full
app to existing AWS host** manually after verifying remaining credits.
It creates no infrastructure and preserves private local configuration.

## External features and checks

The checked-in Google client ID does not establish authorization for the new
CloudFront hostname. Add that HTTPS origin in its Google OAuth client settings.
Google/Gemini are existing external dependencies; hosting is AWS, but the app's
AI provider remains Gemini. Enter a Gemini key privately in
`/srv/taasheera/private/app.env` if the assistant is needed; do not use free-tier
Gemini with real passport data. Configure SMTP privately for password-reset
delivery, using **mhs86@mail.aub.edu** for any required account email. Do not
invent a mailbox or claim SMTP works without a delivery check.

After a private settings change, run `docker compose -f
/opt/taasheera/deploy/aws/compose.yaml up -d --force-recreate api` on the host.
Check HTTPS home page, `/health/ready`, register/login/refresh/logout, upload a
specimen passport, review/save/read it, and confirm data survives a container
restart. Verify assistant and reset-email delivery separately when configured.

## Persistence and deletion

The data volume has Retain policies. Stack deletion deletes the host and releases
the Elastic IP but **does not delete the data volume**; retained EBS continues
to consume credits or incur charges. Back up and explicitly remove it when it is
no longer needed. Host replacement creates a new volume: manually reattach and
restore the retained volume before traffic resumes; no automatic recovery is
claimed. Migration rollback and database backups are manual in this demo setup.
Keep a backup before deploying schema changes. Container updates rerun migrations
and keep the same database, JWT, images, and reviews.
