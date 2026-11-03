#!/usr/bin/env bash
# Install the daily backup timer on the AWS host (US 126). Run once as root, e.g. through
# Systems Manager:  sudo bash /opt/taasheera/deploy/aws/backup/install-backup-timer.sh <bucket-name>
# Writes only outside the /opt/taasheera checkout, which deployments require to stay clean.
set -euo pipefail

bucket="${1:?Usage: install-backup-timer.sh <backup-bucket-name>}"
if ! [[ "$bucket" =~ ^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$ ]]; then
  printf 'Not a valid S3 bucket name.\n' >&2
  exit 2
fi
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p /etc/taasheera
umask 077
printf 'TAASHEERA_BACKUP_BUCKET=%s\nAWS_DEFAULT_REGION=us-east-1\nTAASHEERA_DATA_DIR=/srv/taasheera\n' "$bucket" \
  > /etc/taasheera/backup.env
install -m 644 "$here/taasheera-backup.service" /etc/systemd/system/taasheera-backup.service
install -m 644 "$here/taasheera-backup.timer" /etc/systemd/system/taasheera-backup.timer
systemctl daemon-reload
systemctl enable --now taasheera-backup.timer
systemctl list-timers taasheera-backup.timer --no-pager
printf 'Installed. Run one backup now with: systemctl start taasheera-backup.service\n'
