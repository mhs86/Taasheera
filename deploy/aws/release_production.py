"""Release the checked-out, tested commit to the existing host without rewriting config.

Run from authenticated AWS CloudShell. No dev/main branch is changed. Existing
redeploy tooling backs up SQLite before migrations. Default is a read-only plan.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
from urllib.request import urlopen, Request

from publish_public_policies import Aws, inspect_target

ROOT = Path(__file__).resolve().parents[2]


def revision():
    value = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if not re.fullmatch(r"[a-f0-9]{40}", value):
        raise RuntimeError("An exact Git commit is required.")
    if subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=all"], cwd=ROOT, text=True).strip():
        raise RuntimeError("Commit or stash changes before releasing. The checkout must be clean.")
    return value


def wait_command(aws, instance, command, *, sleep=time.sleep):
    for _ in range(180):
        rows = aws("ssm", "list-command-invocations", "--command-id", command).get("CommandInvocations", [])
        status = rows[0]["Status"] if rows else "Pending"
        if status == "Success":
            return
        if status in {"Failed", "Cancelled", "TimedOut", "Cancelling"}:
            raise RuntimeError(f"Production admin setup failed ({status}); inspect SSM command {command} privately.")
        sleep(10)
    raise RuntimeError(f"SSM command {command} has not completed; check it before retrying.")


def promote(aws, instance, email):
    # Pass the operator-selected email via stdin to Python, not shell interpolation.
    # manage.py validates it and prints only account ID / role, never the address.
    import base64
    encoded = base64.b64encode(email.encode()).decode()
    command = ("set -eu\ncd /opt/taasheera\n"
        "docker compose -f deploy/aws/compose.yaml exec -T api python - <<'TAASHEERA_ADMIN'\n"
        "import base64\nfrom manage import set_role\n"
        f"print(set_role(base64.b64decode('{encoded}').decode(), 'admin'))\nTAASHEERA_ADMIN\n")
    with tempfile.TemporaryDirectory(prefix="taasheera-admin-") as folder:
        parameters = Path(folder) / "parameters.json"
        parameters.write_text(json.dumps({"commands": [command], "executionTimeout": ["120"]}))
        reply = aws("ssm", "send-command", "--instance-ids", instance,
            "--document-name", "AWS-RunShellScript", "--comment", "Set designated existing Taasheera admin",
            "--parameters", "file://" + str(parameters))
    command_id = reply["Command"]["CommandId"]
    print("Admin setup SSM command:", command_id)
    wait_command(aws, instance, command_id)


def get(url, data=None):
    req = Request(url, data=data, headers={"Content-Type": "application/json"} if data else {})
    from urllib.error import HTTPError
    try:
        with urlopen(req, timeout=30) as reply:
            return reply.status, reply.headers.get("Content-Type", ""), reply.read().decode()
    except HTTPError as error:
        return error.code, error.headers.get("Content-Type", ""), error.read().decode()


def verify(origin):
    status, _, text = get(origin + "/health/ready")
    if status != 200:
        raise RuntimeError("Production API readiness failed.")
    status, _, html = get(origin + "/")
    if status != 200:
        raise RuntimeError("Production homepage is unavailable.")
    assets = re.findall(r'<script[^>]+src="(/assets/[^"<>]+\.js)"', html)
    if not assets:
        raise RuntimeError("Production frontend bundle was not found.")
    bundle = "\n".join(get(origin + path)[2] for path in assets)
    if not all(marker in bundle for marker in ["Staff dashboard", "/backoffice", "/apply", "Link Google and sign in", "Add an admin"]):
        raise RuntimeError("Production frontend is missing a required feature. Check the released commit and caching.")
    # Invalid input and anonymous requests cannot create accounts, link or grant roles.
    for path, expected in [("/auth/google/link-login", 422), ("/admin-api/admins/lookup", 401), ("/admin-api/admins", 401)]:
        code, content_type, _ = get(origin + path, b"{}")
        if code != expected or "application/json" not in content_type:
            raise RuntimeError(f"Production API/authentication check failed for {path}.")
    for page in ["privacy.html", "terms.html"]:
        code, content_type, _ = get(origin + "/" + page)
        if code != 200 or "text/html" not in content_type or page not in html:
            raise RuntimeError("Production public policy check failed.")
    print("Verified frontend features, API readiness, anonymous authorization refusals and public policy pages.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--admin-email", help="Optional existing account to promote using the operator CLI")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--stack", default="taasheera")
    args = parser.parse_args()
    if args.admin_email and not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~@-]{3,254}", args.admin_email):
        parser.error("Enter an existing account email address.")
    commit = revision()
    aws = Aws(region=args.region)
    instance, origin = inspect_target(aws, args.stack)
    print(json.dumps({"revision": commit, "instance": instance, "site": origin,
                      "preserve_existing_configuration": True, "set_designated_admin": bool(args.admin_email)}, indent=2))
    if not args.execute:
        print("Read-only plan. Add --execute to release this commit.")
        return
    subprocess.run(["bash", "deploy/aws/redeploy.sh"], cwd=ROOT, check=True,
        env={**os.environ, "TAASHEERA_PRESERVE_CONFIG": "1", "TAASHEERA_STACK": args.stack,
             "AWS_REGION": args.region, "AWS_DEFAULT_REGION": args.region})
    verify(origin)
    if args.admin_email:
        promote(aws, instance, args.admin_email)
        print("Designated existing admin account is configured.")
    print("Production release complete:", origin)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, subprocess.SubprocessError) as error:
        raise SystemExit(str(error)) from None
