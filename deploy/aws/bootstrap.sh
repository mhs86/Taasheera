#!/usr/bin/env bash
# Called through AWS Systems Manager, as root. No application source changes.
set -Eeuo pipefail
phase='validate startup settings'
# Report the step and exit status without exposing command arguments or secrets.
trap 'result=$?; printf "Setup failed during %s (line %s, exit %s).\n" "$phase" "$LINENO" "$result" >&2; exit "$result"' ERR
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
phase='wait for host initialization'
printf 'Setup: %s\n' "$phase"
cloud-init status --wait
systemctl enable --now docker
task_tmp=$(mktemp -d)
trap 'rm -rf "$task_tmp"' EXIT
phase='install verified Docker Compose'
if ! docker compose version >/dev/null 2>&1; then
  compose_version=v2.40.3
  compose_binary=docker-compose-linux-x86_64
  compose_base="https://github.com/docker/compose/releases/download/$compose_version"
  curl --fail --silent --show-error --location "$compose_base/$compose_binary" -o "$task_tmp/$compose_binary"
  curl --fail --silent --show-error --location "$compose_base/checksums.txt" -o "$task_tmp/checksums.txt"
  (cd "$task_tmp" && awk -v name="$compose_binary" '$2 == name || $2 == "*" name {print}' checksums.txt > selected-checksum.txt
    test -s selected-checksum.txt && sha256sum -c selected-checksum.txt)
  install -D -m 755 "$task_tmp/$compose_binary" /usr/local/lib/docker/cli-plugins/docker-compose
fi

phase='install compatible verified Docker Buildx'
printf 'Setup: %s\n' "$phase"
buildx_version=$(docker buildx version 2>/dev/null || true)
if ! python3 - "$buildx_version" <<'PY'
import re, sys
match = re.search(r'\bv(\d+)\.(\d+)\.(\d+)\b', sys.argv[1])
sys.exit(0 if match and tuple(map(int, match.groups())) >= (0, 17, 0) else 1)
PY
then
  buildx_release=v0.31.0
  buildx_binary="buildx-$buildx_release.linux-amd64"
  buildx_base="https://github.com/docker/buildx/releases/download/$buildx_release"
  curl --fail --silent --show-error --location "$buildx_base/$buildx_binary" -o "$task_tmp/$buildx_binary"
  curl --fail --silent --show-error --location "$buildx_base/checksums.txt" -o "$task_tmp/buildx-checksums.txt"
  (cd "$task_tmp" && awk -v name="$buildx_binary" '$2 == name || $2 == "*" name {print}' buildx-checksums.txt > selected-buildx-checksum.txt
    test -s selected-buildx-checksum.txt && sha256sum -c selected-buildx-checksum.txt)
  install -D -m 755 "$task_tmp/$buildx_binary" /usr/local/lib/docker/cli-plugins/docker-buildx
fi
docker buildx version
docker compose version

phase='locate persistent data disk'
printf 'Setup: %s\n' "$phase"
volume_serial=${TAASHEERA_VOLUME_ID//-/}
disk=""
for _attempt in $(seq 1 60); do
  disk=$(lsblk -dn -o PATH,SERIAL | awk -v serial="$volume_serial" '$2 == serial {print $1}')
  test -n "$disk" && break
  sleep 2
done
test -b "$disk"
phase='prepare persistent data filesystem'
printf 'Setup: %s\n' "$phase"
filesystem=$(lsblk -dn -o FSTYPE "$disk")
if [ -z "$filesystem" ]; then
  # Format only the exact newly provisioned, blank data volume, never the root disk.
  test "$(lsblk -nr -o NAME "$disk" | wc -l)" = 1
  wipefs --no-act "$disk" | grep -q . && { echo 'Unknown disk signature; refusing to format.'; exit 1; }
  mkfs.xfs "$disk"
fi
mkdir -p /srv/taasheera
phase='read data filesystem UUID'
disk_uuid=$(blkid -s UUID -o value "$disk")
test -n "$disk_uuid"
phase='mount persistent data disk'
printf 'Setup: %s\n' "$phase"
if mountpoint -q /srv/taasheera; then
  test "$(findmnt -n -o UUID --target /srv/taasheera)" = "$disk_uuid"
else
  mount "$disk" /srv/taasheera
fi
grep -q "UUID=$disk_uuid " /etc/fstab || printf 'UUID=%s /srv/taasheera xfs defaults,nofail 0 2\n' "$disk_uuid" >> /etc/fstab

phase='fetch selected Git commit'
printf 'Setup: %s\n' "$phase"
if [ ! -d /opt/taasheera/.git ]; then
  git clone https://github.com/mhs86/Taasheera.git /opt/taasheera
fi
cd /opt/taasheera
test -z "$(git status --porcelain)"
git fetch origin "$TAASHEERA_REVISION"
git checkout --detach "$TAASHEERA_REVISION"
test -f deploy/aws/compose.yaml

# Preserve JWT across redeployments and host replacement on the retained data disk.
phase='prepare private application configuration'
printf 'Setup: %s\n' "$phase"
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
    'AUTH_TRUST_CLOUDFRONT_PROXY': 'true',
    'PASSPORT_STORAGE_DIR': '/app/storage/passports',
    'ACTIVITY_LOG_DIR': '/app/storage/activity-logs', 'PASSPORT_UPLOADS_ENABLED': 'true',
    'ORIGIN_TOKEN': os.environ['TAASHEERA_ORIGIN_TOKEN'],
    'RESET_MAIL_PROVIDER': 'ses', 'SES_REGION': 'us-east-1',
    'SES_FROM_EMAIL': 'sharafm032@gmail.com',
    'GOOGLE_CLIENT_ID': '1019502864941-452hm5u85t8vcrejuh6aeq43dt85sb9p.apps.googleusercontent.com',
})
# MailSettings requires both the reset URL and SMTP host, or neither. Retrying
# also removes the partial reset setting generated by older bootstrap versions.
if settings.get('SMTP_HOST', '').strip():
    settings.setdefault('RESET_FRONTEND_URL', os.environ['TAASHEERA_SITE_URL'] + '/reset-password')
else:
    settings.pop('RESET_FRONTEND_URL', None)
public = Path('backend/.env.development')
for line in public.read_text().splitlines():
    if line.startswith('GOOGLE_CLIENT_ID='):
        settings.setdefault('GOOGLE_CLIENT_ID', line.split('=', 1)[1])
client_id = os.environ.get('TAASHEERA_GOOGLE_CLIENT_ID', '')
if client_id:
    import re
    if not re.fullmatch(r'[A-Za-z0-9._-]+\.apps\.googleusercontent\.com', client_id):
        raise SystemExit('Invalid Google web client ID.')
    settings['GOOGLE_CLIENT_ID'] = client_id
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
phase='build application images'
printf 'Setup: %s\n' "$phase"
docker compose --parallel 1 -f deploy/aws/compose.yaml build
phase='assign application storage ownership'
api_image=$(docker compose -f deploy/aws/compose.yaml images -q api)
if [ -z "$api_image" ]; then
  api_image=taasheera-api
fi
api_uid=$(docker run --rm --entrypoint id "$api_image" -u)
api_gid=$(docker run --rm --entrypoint id "$api_image" -g)
chown "$api_uid:$api_gid" /srv/taasheera
# Optional settings remain private; the API account cannot read the secret directory.
chmod 700 /srv/taasheera/private
phase='back up the database before migration'
printf 'Setup: %s\n' "$phase"
docker compose -f deploy/aws/compose.yaml stop api web
docker run --rm -i --user 0 --entrypoint python -v /srv/taasheera:/app/storage "$api_image" - <<'PY'
import os, sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
os.umask(0o077)
source = Path('/app/storage/taasheera.db')
if source.is_file():
    directory = Path('/app/storage/private/backups')
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    backup = directory / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid4().hex + '.db')
    with sqlite3.connect(f'file:{source}?mode=ro', uri=True) as database:
        with sqlite3.connect(backup) as destination:
            database.backup(destination)
    backup.chmod(0o600)
    print('Private SQLite backup created before migration.')
else:
    print('No existing database to back up.')
PY
phase='migrate database and start application containers'
printf 'Setup: %s\n' "$phase"
if docker compose -f deploy/aws/compose.yaml up -d --wait --wait-timeout 180; then
  :
else
  result=$?
  # Startup and health errors only: never print Docker inspect environment data.
  docker compose -f deploy/aws/compose.yaml logs --no-color --tail 50 api migrate >&2 || true
  docker inspect taasheera-api-1 --format '{{range .State.Health.Log}}{{println .Output}}{{end}}' >&2 || true
  printf 'Setup failed during %s (exit %s).\n' "$phase" "$result" >&2
  exit "$result"
fi
# Print only readiness status, never request credentials or environment settings.
phase='check API readiness through origin'
curl --fail --silent -H "X-Taasheera-Origin: $TAASHEERA_ORIGIN_TOKEN" http://127.0.0.1/health/ready
