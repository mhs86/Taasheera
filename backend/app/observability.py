"""Request metadata only; never serialize headers, URLs, bodies, or exceptions."""

import json
import logging
import time
from uuid import uuid4

from fastapi import FastAPI, Request


request_log = logging.getLogger("taasheera.requests")


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
        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
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
