#!/usr/bin/env bash
# Update application containers on an existing stack; this creates no AWS resources.
set -euo pipefail
export AWS_PAGER=""
export AWS_CLI_AUTO_PROMPT=off
export AWS_REGION=${AWS_REGION:-us-east-1}
export AWS_DEFAULT_REGION=$AWS_REGION
stack=${TAASHEERA_STACK:-taasheera}
cd "$(dirname "$0")/../.."
export TAASHEERA_REVISION=$(git rev-parse --verify HEAD)
test -z "$(git status --porcelain --untracked-files=all)"
account=$(aws sts get-caller-identity --query Account --output text)
test "$account" = "${TAASHEERA_ACCOUNT_ID:-632630731308}"
task_tmp=$(mktemp -d)
trap 'rm -rf "$task_tmp"' EXIT
umask 077
output() { aws cloudformation describe-stacks --stack-name "$stack" --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue | [0]" --output text; }
export TAASHEERA_INSTANCE_ID=$(output InstanceId)
export TAASHEERA_SITE_URL=$(output SiteUrl)
export TAASHEERA_VOLUME_ID=$(output DataVolumeId)
export TAASHEERA_SSM_FILE="$task_tmp/ssm.json"
python3 - <<'PY'
import base64, json, os, shlex
# Read the existing origin token on the host; it never crosses GitHub Actions logs.
script = base64.b64encode(open('deploy/aws/bootstrap.sh','rb').read()).decode()
prefix = ' '.join(f'{n}={shlex.quote(os.environ[n])}' for n in
                  ['TAASHEERA_SITE_URL','TAASHEERA_VOLUME_ID','TAASHEERA_REVISION'])
command = (f"echo {shlex.quote(script)} | base64 -d > /tmp/taasheera-bootstrap.sh && "
           "export TAASHEERA_ORIGIN_TOKEN=$(sed -n 's/^ORIGIN_TOKEN=//p' /srv/taasheera/private/app.env) && "
           f"{prefix} bash /tmp/taasheera-bootstrap.sh")
with open(os.environ['TAASHEERA_SSM_FILE'],'w') as f:
    json.dump({'commands':[command],'executionTimeout':['1800']}, f)
PY
command_id=$(aws ssm send-command --instance-ids "$TAASHEERA_INSTANCE_ID" --document-name AWS-RunShellScript --parameters "file://$TAASHEERA_SSM_FILE" --query Command.CommandId --output text)
printf 'Application setup started on the existing host (SSM command %s). Builds can take several minutes.\n' "$command_id"
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
