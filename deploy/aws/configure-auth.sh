#!/usr/bin/env bash
# Run once in the owner's AWS CloudShell before deploying dev. No credentials printed.
set -euo pipefail
export AWS_PAGER="" AWS_CLI_AUTO_PROMPT=off
export AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1
stack=${TAASHEERA_STACK:-taasheera}
sender=sharafm032@gmail.com
account=$(aws sts get-caller-identity --query Account --output text)
test "$account" = 632630731308 || { echo 'Wrong AWS account; no changes made.' >&2; exit 1; }
verified=$(aws sesv2 get-email-identity --email-identity "$sender" --query VerifiedForSendingStatus --output text)
test "$verified" = True || { echo 'Verify the Gmail sender in SES us-east-1 first.' >&2; exit 1; }
aws sesv2 get-account --query '{SendingEnabled:SendingEnabled,ProductionAccessEnabled:ProductionAccessEnabled,Quota:SendQuota}' --output json
role=$(aws cloudformation describe-stack-resource --stack-name "$stack" --logical-resource-id HostRole --query StackResourceDetail.PhysicalResourceId --output text)
instance=$(aws cloudformation describe-stacks --stack-name "$stack" --query "Stacks[0].Outputs[?OutputKey=='InstanceId'].OutputValue | [0]" --output text)
[[ "$role" =~ ^[A-Za-z0-9+=,.@_-]+$ ]]
[[ "$instance" =~ ^i-[a-f0-9]+$ ]]
task_tmp=$(mktemp -d)
trap 'rm -rf "$task_tmp"' EXIT
umask 077
cat > "$task_tmp/ses-policy.json" <<'JSON'
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": "ses:SendEmail",
    "Resource": "arn:aws:ses:us-east-1:632630731308:identity/sharafm032@gmail.com",
    "Condition": {"StringEquals": {"ses:FromAddress": "sharafm032@gmail.com"}}
  }]
}
JSON
aws iam put-role-policy --role-name "$role" --policy-name TaasheeraResetEmail --policy-document "file://$task_tmp/ses-policy.json"
# Two hops are needed for IMDSv2 replies to reach the private Docker network.
aws ec2 modify-instance-metadata-options --instance-id "$instance" \
  --http-tokens required --http-put-response-hop-limit 2 \
  --query 'InstanceMetadataOptions.{State:State,HttpTokens:HttpTokens,HttpPutResponseHopLimit:HttpPutResponseHopLimit}' --output json
printf 'SES sender permission configured. Run bash deploy/aws/redeploy.sh from the tested dev commit.\n'
