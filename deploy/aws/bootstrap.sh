#!/usr/bin/env bash
# Called through AWS Systems Manager, as root. No application source changes.
set -euo pipefail
test "$(id -u)" = 0
: "${TAASHEERA_REVISION:?Full Git commit required}"
: "${TAASHEERA_SITE_URL:?HTTPS CloudFront origin required}"
: "${TAASHEERA_VOLUME_ID:?Persistent EBS volume required}"
: "${TAASHEERA_ORIGIN_TOKEN:?CloudFront origin token required}"
[[ "$TAASHEERA_REVISION" =~ ^[a-f0-9]{40}$ ]]
[[ "$TAASHEERA_SITE_URL" =~ ^https://[a-z0-9]+\.cloudfront\.net$ ]]
[[ "$TAASHEERA_VOLUME_ID" =~ ^vol-[a-f0-9]+$ ]]
[[ "$TAASHEERA_ORIGIN_TOKEN" =~ ^[a-f0-9]{64}$ ]]
umask 077

# cloud-init installs the packages and starts Docker.
cloud-init status --wait
systemctl enable --now docker
if ! docker compose version >/dev/null 2>&1; then
  task_tmp=$(mktemp -d)
  trap 'rm -rf "$task_tmp"' EXIT
  compose_version=v2.40.3
  compose_binary=docker-compose-linux-x86_64
  compose_base="https://github.com/docker/compose/releases/download/$compose_version"
  curl --fail --location "$compose_base/$compose_binary" -o "$task_tmp/$compose_binary"
  curl --fail --location "$compose_base/checksums.txt" -o "$task_tmp/checksums.txt"
  (cd "$task_tmp" && awk -v name="$compose_binary" '$2 == name || $2 == "*" name {print}' checksums.txt > selected-checksum.txt
    test -s selected-checksum.txt && sha256sum -c selected-checksum.txt)
  install -D -m 755 "$task_tmp/$compose_binary" /usr/local/lib/docker/cli-plugins/docker-compose
fi

volume_serial=${TAASHEERA_VOLUME_ID//-/}
disk=""
for attempt in $(seq 1 60); do
  disk=$(lsblk -dn -o PATH,SERIAL | awk -v serial="$volume_serial" '$2 == serial {print $1}')
  test -n "$disk" && break
  sleep 2
done
test -b "$disk"
filesystem=$(lsblk -dn -o FSTYPE "$disk")
if [ -z "$filesystem" ]; then
  # Format only the exact newly provisioned, blank data volume, never the root disk.
  test "$(lsblk -nr -o NAME "$disk" | wc -l)" = 1
  wipefs --no-act "$disk" | grep -q . && { echo 'Unknown disk signature; refusing to format.'; exit 1; }
  mkfs.xfs "$disk"
fi
mkdir -p /srv/taasheera
disk_uuid=$(blkid -s UUID -o value "$disk")
test -n "$disk_uuid"
if mountpoint -q /srv/taasheera; then
  test "$(findmnt -n -o UUID --target /srv/taasheera)" = "$disk_uuid"
else
  mount "$disk" /srv/taasheera
fi
grep -q "UUID=$disk_uuid " /etc/fstab || printf 'UUID=%s /srv/taasheera xfs defaults,nofail 0 2\n' "$disk_uuid" >> /etc/fstab

if [ ! -d /opt/taasheera/.git ]; then
  git clone https://github.com/mhs86/Taasheera.git /opt/taasheera
fi
cd /opt/taasheera
test -z "$(git status --porcelain)"
git fetch origin "$TAASHEERA_REVISION"
git checkout --detach "$TAASHEERA_REVISION"
test -f deploy/aws/compose.yaml

# Preserve JWT across redeployments and host replacement on the retained data disk.
mkdir -p /srv/taasheera/private /etc/taasheera
if [ ! -f /srv/taasheera/private/app.env ]; then
  python3 - <<'PY'
import os, secrets
with open('/srv/taasheera/private/app.env', 'x') as f:
    f.write('JWT_SECRET=' + secrets.token_urlsafe(48) + '\n')
PY
fi
python3 - <<'PY'
import os
from pathlib import Path
path = Path('/srv/taasheera/private/app.env')
settings = dict(line.split('=', 1) for line in path.read_text().splitlines() if '=' in line)
settings.update({
    'APP_ENV': 'production', 'SCHEMA_AUTO_CREATE': 'false', 'REQUIRE_TESSERACT': 'true',
    'DATABASE_URL': 'sqlite:////app/storage/taasheera.db',
    'AUTH_ALLOWED_ORIGINS': os.environ['TAASHEERA_SITE_URL'], 'AUTH_COOKIE_SECURE': 'true',
    'PASSPORT_STORAGE_DIR': '/app/storage/passports',
    'ACTIVITY_LOG_DIR': '/app/storage/activity-logs', 'PASSPORT_UPLOADS_ENABLED': 'true',
    'ORIGIN_TOKEN': os.environ['TAASHEERA_ORIGIN_TOKEN'],
    'RESET_FRONTEND_URL': os.environ['TAASHEERA_SITE_URL'] + '/reset-password',
})
public = Path('backend/.env.development')
for line in public.read_text().splitlines():
    if line.startswith('GOOGLE_CLIENT_ID='):
        settings.setdefault('GOOGLE_CLIENT_ID', line.split('=', 1)[1])
tmp = path.with_suffix('.tmp')
tmp.write_text(''.join(f'{k}={v}\n' for k,v in settings.items()))
tmp.chmod(0o600)
tmp.replace(path)
web = path.with_name('web.env')
web.write_text('ORIGIN_TOKEN=' + settings['ORIGIN_TOKEN'] + '\n')
web.chmod(0o600)
PY
ln -sfn /srv/taasheera/private/app.env /etc/taasheera/app.env
ln -sfn /srv/taasheera/private/web.env /etc/taasheera/web.env

# Resolve the image's user rather than relying on a distribution-specific UID.
docker compose --parallel 1 -f deploy/aws/compose.yaml build
api_image=$(docker compose -f deploy/aws/compose.yaml images -q api)
if [ -z "$api_image" ]; then
  api_image=taasheera-api
fi
api_uid=$(docker run --rm --entrypoint id "$api_image" -u)
api_gid=$(docker run --rm --entrypoint id "$api_image" -g)
chown "$api_uid:$api_gid" /srv/taasheera
# Optional settings remain private; the API account cannot read the secret directory.
chmod 700 /srv/taasheera/private
docker compose -f deploy/aws/compose.yaml up -d --wait --wait-timeout 180
# Print only readiness status, never request credentials or environment settings.
curl --fail --silent -H "X-Taasheera-Origin: $TAASHEERA_ORIGIN_TOKEN" http://127.0.0.1/health/ready
