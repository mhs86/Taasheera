"""Request metadata only; never serialize headers, URLs, bodies, or exceptions."""

import json
import logging
import time
from uuid import uuid4

from fastapi import FastAPI, Request


request_log = logging.getLogger("taasheera.requests")


def install_private_no_store(app: FastAPI) -> None:
    private_prefixes = ("/auth", "/passports", "/profile", "/sessions", "/activity", "/applications", "/assistant")

    @app.middleware("http")
    async def no_store(request: Request, call_next):
        response = await call_next(request)
        path, root = request.scope["path"], request.scope.get("root_path", "")
        if root and path.startswith(root + "/"):
            path = path[len(root):]
        if any(path == prefix or path.startswith(prefix + "/") for prefix in private_prefixes):
            # Preserve the explicit private directive used for passport images.
            response.headers.setdefault("Cache-Control", "no-store")
        return response


class RequestJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(record.activity, separators=(",", ":"))


def install_request_logging(app: FastAPI) -> None:
    if not request_log.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(RequestJsonFormatter())
        request_log.addHandler(handler)
    request_log.setLevel(logging.INFO)
    request_log.propagate = False

    @app.middleware("http")
    async def record_request(request: Request, call_next):
        request_id = uuid4().hex
        request.state.request_id = request_id
        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            if status_code >= 500:
                from .monitoring import capture_service_error
                capture_service_error(request)
                owner_id = getattr(request.state, "traveler_id", None)
                if owner_id is not None:
                    from sqlmodel import Session
                    from .activity import record_activity
                    try:
                        with Session(request.app.state.engine) as session:
                            record_activity(session, request.app.state.activity_directory, owner_id,
                                "api_error", getattr(request.scope.get("route"), "path", "unmatched")[:80], "error")
                    except Exception:
                        # Monitoring must preserve the original response/exception.
                        logging.getLogger(__name__).error("Could not persist service error metadata")
            # FastAPI has populated the route template, which contains no
            # traveler IDs, reset tokens, query strings, or submitted values.
            route = request.scope.get("route")
            route_path = getattr(route, "path", "unmatched")
            request_log.info("request", extra={"activity": {
                "request_id": request_id,
                "method": request.method,
                "route": route_path,
                "status": status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            }})
