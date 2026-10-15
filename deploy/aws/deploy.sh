#!/usr/bin/env bash
# Run from a configured AWS CloudShell or an authenticated workstation.
set -euo pipefail
export AWS_PAGER=""
export AWS_CLI_AUTO_PROMPT=off
: "${AWS_FREE_ELIGIBILITY_CONFIRMED:?Set to yes only after verifying AWS plan, credits, and service eligibility}"
test "$AWS_FREE_ELIGIBILITY_CONFIRMED" = yes
export AWS_REGION=${AWS_REGION:-us-east-1}
export AWS_DEFAULT_REGION=$AWS_REGION
stack=${TAASHEERA_STACK:-taasheera}
task_root=$(cd "$(dirname "$0")/../.." && pwd)
cd "$task_root"
revision=$(git rev-parse --verify HEAD)
# The instance fetches this commit. Publish configuration files before deploying.
test -z "$(git status --porcelain --untracked-files=all)"
account=$(aws sts get-caller-identity --query Account --output text)
test "$account" = "${TAASHEERA_ACCOUNT_ID:-632630731308}"
umask 077
state_dir="${TAASHEERA_STATE_DIR:-$task_root/.aws-deploy-state}"
mkdir -p "$state_dir"
if [ ! -f "$state_dir/origin-token" ]; then
  python3 -c 'import secrets; print(secrets.token_hex(32))' > "$state_dir/origin-token"
fi
origin_token=$(cat "$state_dir/origin-token")
vpc=${TAASHEERA_VPC_ID:-$(aws ec2 describe-vpcs --filters Name=is-default,Values=true --query 'Vpcs[0].VpcId' --output text)}
test "$vpc" != None
subnet=${TAASHEERA_SUBNET_ID:-$(aws ec2 describe-subnets --filters "Name=vpc-id,Values=$vpc" Name=map-public-ip-on-launch,Values=true --query 'Subnets[0].SubnetId' --output text)}
test "$subnet" != None
prefix=$(aws ec2 describe-managed-prefix-lists --filters Name=prefix-list-name,Values=com.amazonaws.global.cloudfront.origin-facing --query 'PrefixLists[0].PrefixListId' --output text)
test "$prefix" != None
export TAASHEERA_PARAMETER_FILE="$state_dir/parameters.json"
export TAASHEERA_ORIGIN_TOKEN="$origin_token"
export TAASHEERA_VPC_ID="$vpc" TAASHEERA_SUBNET_ID="$subnet" TAASHEERA_PREFIX_ID="$prefix"
python3 - <<'PY'
import json, os
parameters = {'OwnerEmail': 'mhs86@mail.aub.edu', 'VpcId': os.environ['TAASHEERA_VPC_ID'],
              'SubnetId': os.environ['TAASHEERA_SUBNET_ID'],
              'CloudFrontPrefixListId': os.environ['TAASHEERA_PREFIX_ID'],
              'OriginToken': os.environ['TAASHEERA_ORIGIN_TOKEN']}
with open(os.environ['TAASHEERA_PARAMETER_FILE'], 'w') as f:
    json.dump([{'ParameterKey':k, 'ParameterValue':v} for k,v in parameters.items()], f)
PY
change_set="$stack-$(date +%s)"
change_type=CREATE
if aws cloudformation describe-stacks --stack-name "$stack" > "$state_dir/stack.json" 2> "$state_dir/stack-error.log"; then
  change_type=UPDATE
else
  grep -q 'does not exist' "$state_dir/stack-error.log" || { cat "$state_dir/stack-error.log"; exit 1; }
fi
aws cloudformation create-change-set --stack-name "$stack" --change-set-name "$change_set" \
  --change-set-type "$change_type" --template-body file://deploy/aws/stack.yaml \
  --parameters "file://$TAASHEERA_PARAMETER_FILE" --capabilities CAPABILITY_IAM >/dev/null
if aws cloudformation wait change-set-create-complete --stack-name "$stack" --change-set-name "$change_set"; then
  # Show only resource changes; NoEcho parameters are not printed.
  aws cloudformation describe-change-set --stack-name "$stack" --change-set-name "$change_set" --query Changes
  if [ "${TAASHEERA_EXECUTE_CHANGE_SET:-no}" != yes ]; then
    printf 'Prepared change set %s. Review resources and costs, then execute it and run this script again.\n' "$change_set"
    exit 0
  fi
  aws cloudformation execute-change-set --stack-name "$stack" --change-set-name "$change_set"
  printf 'Waiting for CloudFormation %s to finish; this can take several minutes.\n' "$change_type"
  if [ "$change_type" = CREATE ]; then
    aws cloudformation wait stack-create-complete --stack-name "$stack"
  else
    aws cloudformation wait stack-update-complete --stack-name "$stack"
  fi
else
  reason=$(aws cloudformation describe-change-set --stack-name "$stack" --change-set-name "$change_set" --query StatusReason --output text)
  [[ "$reason" == *"didn't contain changes"* || "$reason" == *"No updates"* ]] || { printf '%s\n' "$reason"; exit 1; }
fi
output() { aws cloudformation describe-stacks --stack-name "$stack" --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue | [0]" --output text; }
TAASHEERA_INSTANCE_ID=$(output InstanceId)
export TAASHEERA_INSTANCE_ID
TAASHEERA_SITE_URL=$(output SiteUrl)
export TAASHEERA_SITE_URL
TAASHEERA_VOLUME_ID=$(output DataVolumeId)
export TAASHEERA_VOLUME_ID
export TAASHEERA_REVISION="$revision"
for attempt in $(seq 1 60); do
  status=$(aws ssm describe-instance-information --filters "Key=InstanceIds,Values=$TAASHEERA_INSTANCE_ID" --query 'InstanceInformationList[0].PingStatus' --output text)
  test "$status" = Online && break
  sleep 5
done
test "$status" = Online
export TAASHEERA_SSM_FILE="$state_dir/ssm.json"
python3 - <<'PY'
import base64, json, os, shlex
script = base64.b64encode(open('deploy/aws/bootstrap.sh','rb').read()).decode()
names = ['TAASHEERA_SITE_URL','TAASHEERA_VOLUME_ID','TAASHEERA_REVISION','TAASHEERA_ORIGIN_TOKEN']
prefix = ' '.join(f'{n}={shlex.quote(os.environ[n])}' for n in names)
command = f"echo {shlex.quote(script)} | base64 -d > /tmp/taasheera-bootstrap.sh && {prefix} bash /tmp/taasheera-bootstrap.sh"
with open(os.environ['TAASHEERA_SSM_FILE'],'w') as f:
    json.dump({'commands':[command], 'executionTimeout':['1800']},f)
PY
command_id=$(aws ssm send-command --instance-ids "$TAASHEERA_INSTANCE_ID" --document-name AWS-RunShellScript --parameters "file://$TAASHEERA_SSM_FILE" --query Command.CommandId --output text)
printf 'Application setup started (SSM command %s). Builds can take several minutes.\n' "$command_id"
last_status=''
for attempt in $(seq 1 180); do
  status=$(aws ssm list-command-invocations --command-id "$command_id" --query 'CommandInvocations[0].Status' --output text)
  if [ "$status" != "$last_status" ] || (( attempt % 6 == 0 )); then
    printf 'Application setup status: %s\n' "$status"
    last_status=$status
  fi
  case "$status" in
    Success) break;;
    Failed|Cancelled|TimedOut)
      echo "Application setup failed (SSM command $command_id)."
      aws ssm get-command-invocation --command-id "$command_id" --instance-id "$TAASHEERA_INSTANCE_ID" \
        --query '{Status:Status,ExitCode:ResponseCode,Error:StandardErrorContent}' --output json
      exit 1;;
  esac
  sleep 10
done
test "$status" = Success
curl --fail --silent --show-error "$TAASHEERA_SITE_URL/health/ready"
printf '\nHTTPS site: %s\n' "$TAASHEERA_SITE_URL"
