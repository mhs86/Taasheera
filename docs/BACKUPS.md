# Backups and restore (US 126)

Every night the AWS host backs up the database and the passport files to a private,
encrypted S3 bucket. A restore checks a backup completely before it changes anything,
keeps the data it replaces, migrates the schema and checks that the API is ready.
The tool is `backend/scripts/backup_tools.py` (standard library only, because the host
runs it with Amazon Linux's Python 3.9); its tests are `backend/tests/test_backup.py`.

## What is in a backup

| Included | Not included |
|---|---|
| `taasheera.db`: a consistent copy made with SQLite's online backup while the API keeps running, checked with `PRAGMA integrity_check` | `private/app.env` and `web.env` (JWT secret, origin token): they are recreated by `bootstrap.sh`, and must never sit in a bucket |
| `passports/`: every uploaded passport image | the pre-migration copies in `private/backups/*.db` |
| `activity-logs/`: the per-traveler JSONL mirrors | the containers and code (they come from Git) |
| `manifest.json`: time, schema revision, row counts, and a SHA-256 for every file | |

Each archive is `db/<UTC time>.tar.gz` with a `.sha256` beside it. The host keeps the
newest 7 in `/srv/taasheera/private/backups/scheduled/` (mode 0700, files 0600); the bucket
keeps each one for 30 days. If the server dies at the wrong moment, up to a day of changes
can be lost. Only the SQLite deployment is supported; PostgreSQL would need `pg_dump`
instead, which is not built.

Backups contain passport data. The bucket blocks all public access, refuses non-HTTPS
requests, encrypts every object (SSE-S3) and keeps old versions. The host can write and read
backups but has no permission to delete them; S3 lifecycle rules remove old ones. A
compromised host could still overwrite a backup, but the overwritten copy stays as an old
version for the same 30 days. Never share presigned links to backup objects.

## One-time setup (AWS)

1. Create the bucket and the host's policy. `HostRoleName` is the EC2 role from
   `deploy/aws/stack.yaml` (CloudFormation console, stack resources, `HostRole`):

   ```bash
   aws cloudformation deploy --region us-east-1 --stack-name taasheera-backups \
     --template-file deploy/aws/backup-bucket.yaml --capabilities CAPABILITY_IAM \
     --parameter-overrides HostRoleName=<host-role-name>
   aws cloudformation describe-stacks --region us-east-1 --stack-name taasheera-backups \
     --query "Stacks[0].Outputs[?OutputKey=='BucketName'].OutputValue" --output text
   ```

   Don't commit the bucket name: it contains the AWS account ID.
2. Install the timer on the host (Systems Manager, Session Manager or Run Command):

   ```bash
   sudo bash /opt/taasheera/deploy/aws/backup/install-backup-timer.sh <bucket-name>
   ```

   It writes `/etc/taasheera/backup.env` and the two systemd units, and touches nothing in
   `/opt/taasheera` (deployments require that checkout to stay clean). A redeploy keeps it.
3. Run one backup now and check it:

   ```bash
   sudo systemctl start taasheera-backup.service
   sudo journalctl -u taasheera-backup.service -n 20 --no-pager
   aws s3 ls s3://<bucket-name>/db/
   ```

A failed backup leaves the service in the `failed` state (`systemctl --failed`), with the
reason in the journal. Errors never print file names (they contain traveler IDs) or command
lines (one holds the origin token). Each backup is unpacked and checked once before it is
uploaded, and a run that takes over an hour is stopped. A backup and a restore never run at
the same time.

## Restore

Run on the host as root. First check the backup without changing anything:

```bash
sudo bash -c 'set -a; . /etc/taasheera/backup.env; set +a; cd /opt/taasheera && python3 backend/scripts/backup_tools.py restore --latest'
```

Use `--key db/<name>.tar.gz` for a particular backup, or `--archive <file>` for one already on
the host (its `.sha256` must sit beside it). It downloads into `private/restore/`, checks the
checksum, refuses entries outside the backup layout, compares every file with the manifest
and runs SQLite's integrity check. It then prints the schema revision and row counts.

To put it in place, run the same command with `--yes`. The site is down for a few minutes:

1. stops the `web` and `api` containers;
2. keeps the current database, passports and activity logs in `private/pre-restore-<time>/`
   (moved there, not deleted, so anything written since the backup can still be recovered);
3. moves the backup into place and gives it to the API's account;
4. runs `migrate` (a backup from an older schema is upgraded), starts the containers and
   waits for them to be healthy;
5. checks `/health/ready` through the origin header.

Remove `private/pre-restore-*` by hand once the restore is confirmed; it takes disk space and
holds passport data. Downloaded archives and the staging folder are removed automatically.

### If a restore fails

Before the swap (download, checksum, integrity check), nothing has changed and the site is
still up. If stopping the containers fails, start them again:
`sudo docker compose -f /opt/taasheera/deploy/aws/compose.yaml up -d`.

After the swap, the error names the step (the migration, starting the containers, or the
readiness check) and the `pre-restore-<time>` folder. The backup is in place and the site may be
down. Read `docker compose -f /opt/taasheera/deploy/aws/compose.yaml logs --tail 50 api migrate`,
fix the cause and run `up -d` again. To go back to the data from before the restore instead,
stop the containers, move `taasheera.db`, `passports/` and `activity-logs/` from that folder
back into `/srv/taasheera/`, then run `up -d`.

## Rehearsal

Rehearse after setup, and after any change to the tool or the storage layout. Prefer a
quiet time and specimen data. Write down what really happened; don't fill rows in advance.

1. Note the row counts. The host has no `sqlite3` command, so use Python:
   `sudo python3 -c "import sqlite3; print(sqlite3.connect('file:/srv/taasheera/taasheera.db?mode=ro', uri=True).execute('select count(*) from traveler').fetchone())"`
   (or read them from the check-only command's output).
2. Run a backup (`systemctl start taasheera-backup.service`) and confirm the object in S3.
3. Restore it with `--latest --yes`, timing it.
4. Check that the counts match, sign in with a test account, and open a passport review page.

### Rehearsal log

| Date | Who | Backup key | Size | Check-only result | Rows before / after | Time to restore | Readiness | Issues |
|---|---|---|---|---|---|---|---|---|
| | | | | | | | | |

The tool's own round trip (back up, damage the live data, restore, compare rows and files) runs
in CI on every pull request: `backend/tests/test_backup.py`.
