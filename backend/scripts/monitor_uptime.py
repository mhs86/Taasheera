"""Bounded readiness probe; optional team webhook receives no URL or credentials."""
import json
import os
import sys
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def check_uptime(url, *, opener=urlopen, attempts=3):
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("UPTIME_URL must be an HTTP(S) readiness URL without credentials.")
    for _ in range(attempts):
        try:
            with opener(Request(url, headers={"Accept": "application/json"}), timeout=10) as response:
                if response.status == 200 and json.loads(response.read(4096)).get("status") == "ok":
                    return True
        except (URLError, OSError, ValueError, AttributeError):
            pass
    return False


def alert_team(webhook, *, opener=urlopen):
    parsed = urlsplit(webhook)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("UPTIME_ALERT_WEBHOOK must be HTTPS without credentials in userinfo.")
    request = Request(webhook, method="POST", headers={"Content-Type": "application/json"},
                      data=json.dumps({"text": "Taasheera readiness check failed three times. Follow the monitoring runbook."}).encode())
    with opener(request, timeout=10) as response:
        if not 200 <= response.status < 300:
            raise ValueError("Alert was not accepted")


def main():
    url = os.environ.get("UPTIME_URL", "")
    if not url:
        raise SystemExit("Set UPTIME_URL to the service /health/ready endpoint.")
    try:
        healthy = check_uptime(url)
        if not healthy:
            webhook = os.environ.get("UPTIME_ALERT_WEBHOOK", "")
            if webhook:
                alert_team(webhook)
            print("Taasheera readiness probe failed.", file=sys.stderr)
            return 1
    except (ValueError, URLError, OSError):
        print("Probe or alert configuration failed. Check the private configuration.", file=sys.stderr)
        return 1
    print("Taasheera readiness probe passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
