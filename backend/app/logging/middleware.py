"""M4 — structured request logging + request tracing.

Every HTTP request is logged once as a single JSON line carrying:
``request_id`` (also echoed to the client as ``x-request-id``), method,
path, status, latency_ms, and the caller scope (user id + audience decoded
from the Bearer token without a DB round-trip). Log lines go to journald
on the shared host via the existing stderr handler — no new container,
no in-process scheduler (rule 5).

The ``x-request-id`` header lets an admin correlate a browser console
message with the exact backend log line while the service is idle-stopped.
"""

from __future__ import annotations

import json
import logging
import time
import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.auth.jwt_handler import verify_token

logger = logging.getLogger("app.request")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Attach a request id, echo it, and log one JSON line per request."""

    async def dispatch(self, request: Request, call_next):
        request_id = uuid.uuid4().hex[:16]
        request.state.request_id = request_id

        start = time.perf_counter()
        status_code = None
        error = None
        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception as exc:  # noqa: BLE001 - log then re-raise
            status_code = 500
            error = type(exc).__name__
            raise
        finally:
            latency_ms = (time.perf_counter() - start) * 1000.0
            record = {
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status": status_code,
                "latency_ms": round(latency_ms, 2),
                "user_id": None,
                "audience": None,
                "client_ip": request.client.host if request.client else None,
            }
            auth = request.headers.get("authorization")
            if auth and auth.lower().startswith("bearer "):
                payload = verify_token(auth[7:])
                if payload:
                    record["user_id"] = payload.get("sub")
                    record["audience"] = payload.get("audience")
            if error:
                record["error"] = error
            logger.info(json.dumps(record, default=str))
        response.headers["x-request-id"] = request_id
        return response