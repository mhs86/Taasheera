"""Publish public consent-policy pages to the existing AWS host, without an app release.

Requires AWS CLI authentication for the existing account and SSM access to the
stack host. Default is a read-only plan. --execute publishes the prepared files.
"""
import argparse
import base64
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
ACCOUNT = "632630731308"
ASSETS = ("privacy.html", "terms.html", "legal.css")


class Aws:
    def __init__(self, cli="aws", region="us-east-1"):
        self.cli, self.region = cli, region

    def __call__(self, *args):
        try:
            result = subprocess.run([self.cli, "--region", self.region, *args,
                "--output", "json"], check=True, capture_output=True, text=True, timeout=60,
                env={**os.environ, "AWS_PAGER": "", "AWS_CLI_AUTO_PROMPT": "off"})
        except FileNotFoundError:
            raise RuntimeError("AWS CLI is missing. Run this from authenticated AWS CloudShell.") from None
        except subprocess.CalledProcessError as error:
            if "Unable to locate credentials" in error.stderr:
                raise RuntimeError("AWS is not authenticated. Connect the AWS account or use authenticated CloudShell.") from None
            raise RuntimeError(f"AWS {args[0]} {args[1]} failed. Check the account, region and IAM permissions.") from None
        return json.loads(result.stdout)


def inspect_target(aws, stack):
    if aws("sts", "get-caller-identity").get("Account") != ACCOUNT:
        raise ValueError("Refusing changes: this is not the documented Taasheera AWS account.")
    data = aws("cloudformation", "describe-stacks", "--stack-name", stack)
    outputs = {item["OutputKey"]: item["OutputValue"] for item in data["Stacks"][0]["Outputs"]}
    instance, origin = outputs["InstanceId"], outputs["SiteUrl"].rstrip("/")
    parsed = urlsplit(origin)
    if not re.fullmatch(r"i-[0-9a-f]{8,17}", instance):
        raise ValueError("The stack did not identify a valid existing instance.")
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.path or parsed.query or parsed.fragment or parsed.port not in (None, 443)):
        raise ValueError("The existing stack must supply an exact public HTTPS site origin.")
    return instance, origin


def make_command(origin, google_token=None):
    if google_token is not None and not re.fullmatch(r"[A-Za-z0-9_-]{10,300}", google_token):
        raise ValueError("Use only the public verification meta-tag content from Google Search Console.")
    assets = {name: base64.b64encode((ROOT / "frontend/public" / name).read_bytes()).decode() for name in ASSETS}
    payload = {"site_url": origin, "assets": assets,
        "worker": (ROOT / "deploy/aws/install_public_policies.py").read_text(),
        "google_verification": google_token}
    payload["bundle_sha256"] = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    packed = base64.b64encode(gzip.compress(json.dumps(payload).encode(), mtime=0)).decode()
    command = """set -eu
umask 077
python3 - <<'TAASHEERA_PUBLIC_POLICIES'
import base64,gzip,json,pathlib,subprocess,sys,tempfile
payload=json.loads(gzip.decompress(base64.b64decode('__PAYLOAD__')))
with tempfile.TemporaryDirectory(prefix='taasheera-public-policies-') as folder:
    root=pathlib.Path(folder)
    worker=root/'install.py'
    worker.write_text(payload.pop('worker'))
    inputs=root/'payload.json'
    inputs.write_text(json.dumps(payload))
    subprocess.run([sys.executable,str(worker),str(inputs)],check=True)
TAASHEERA_PUBLIC_POLICIES
""".replace("__PAYLOAD__", packed)
    if len(command.encode()) > 24000:
        raise ValueError("Public policy payload exceeds the bounded SSM command size.")
    return command, payload["bundle_sha256"]


def publish(aws, stack="taasheera", *, execute=False, google_token=None, sleep=time.sleep):
    instance, origin = inspect_target(aws, stack)
    command, digest = make_command(origin, google_token)
    print(json.dumps({"site": origin, "instance": instance, "bundle_sha256": digest,
        "homepage": origin + "/", "privacy": origin + "/privacy.html", "terms": origin + "/terms.html"}, indent=2))
    if not execute:
        print("Read-only plan. Add --execute to publish public files on the existing web host.")
        return
    with tempfile.TemporaryDirectory(prefix="taasheera-policy-command-") as folder:
        parameters = Path(folder) / "parameters.json"
        parameters.write_text(json.dumps({"commands": [command], "executionTimeout": ["240"]}))
        response = aws("ssm", "send-command", "--instance-ids", instance,
            "--document-name", "AWS-RunShellScript", "--comment", "Publish Taasheera public privacy and terms pages",
            "--parameters", "file://" + str(parameters))
    command_id = response["Command"]["CommandId"]
    print("Publishing through SSM command:", command_id)
    for _ in range(100):
        result = aws("ssm", "list-command-invocations", "--command-id", command_id, "--details")
        invocations = result.get("CommandInvocations", [])
        status = invocations[0]["Status"] if invocations else "Pending"
        if status == "Success":
            print("Published and verified all policy URLs, homepage links and existing API readiness.")
            return
        if status in {"Failed", "Cancelled", "TimedOut", "Cancelling"}:
            raise RuntimeError(f"Publishing did not complete (SSM {command_id}, {status}). Inspect the command and public-file rollback in AWS.")
        sleep(3)
    raise RuntimeError(f"SSM {command_id} is still running. Check its status before retrying.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--stack", default="taasheera")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--aws-cli", default="aws")
    parser.add_argument("--google-site-verification", help="Optional public meta-tag content from Google Search Console")
    args = parser.parse_args()
    try:
        publish(Aws(args.aws_cli, args.region), args.stack, execute=args.execute, google_token=args.google_site_verification)
    except (RuntimeError, ValueError, KeyError, subprocess.SubprocessError) as error:
        raise SystemExit(str(error)) from None


if __name__ == "__main__":
    main()
