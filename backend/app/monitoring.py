"""Opt-in error reporting with an allowlist, rather than best-effort PII removal."""
import os
from urllib.parse import urlsplit

import sentry_sdk


def scrub_event(event, hint):
    # No request, user, headers, breadcrumbs, local variables, paths or exception messages.
    result = {key: event[key] for key in ("event_id", "timestamp", "platform", "level", "environment", "release")
              if key in event}
    result["message"] = "Taasheera service error"
    tags = event.get("tags", {})
    result["tags"] = {key: tags[key] for key in ("request_id", "component") if key in tags}
    return result


def configure_monitoring():
    dsn = os.environ.get("SENTRY_DSN", "").strip()
    if not dsn:
        return None
    try:
        parsed = urlsplit(dsn)
        valid = parsed.scheme == "https" and parsed.hostname and parsed.username and parsed.path.strip("/")
    except ValueError:
        valid = False
    if not valid:
        raise RuntimeError("SENTRY_DSN must be an HTTPS Sentry DSN.")
    sentry_sdk.init(dsn=dsn, environment=os.environ.get("APP_ENV", "development"),
        send_default_pii=False, default_integrations=False, before_send=scrub_event,
        traces_sample_rate=0, max_request_body_size="never")
    return sentry_sdk.get_client()


def capture_service_error(request):
    if not os.environ.get("SENTRY_DSN", "").strip():
        return
    with sentry_sdk.new_scope() as scope:
        scope.set_tag("request_id", request.state.request_id)
        scope.set_tag("component", "backend")
        sentry_sdk.capture_message("Taasheera service error", level="error")
