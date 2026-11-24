"""Logging and request tracing for container hosting.

* ``configure_logging()`` - text lines for a terminal, or one JSON object per line (LOG_FORMAT=json) for a log
  service. The JSON form carries the request id of the request being handled, so a slow search or an error can
  be followed across lines without any personal data: no query strings, no search words, no names.
* ``RequestContextMiddleware`` - gives every request an id (``X-Request-ID``, taken from the proxy when it sends
  one), returns it in the response, and with ACCESS_LOG=true writes one line per request: method, path, status
  and duration. The query string is deliberately not logged (it holds what people searched for).
* ``/api/ready`` (in main.py) - readiness for a container platform: answers 503 until the database and the
  sign-in store can be reached, so no traffic is routed to a replica that cannot serve it.
"""
from __future__ import annotations

import contextvars
import json
import logging
import re
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from .config import settings

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_var.get(),
            "environment": settings.environment,
        }
        for key in ("method", "path", "status", "ms"):
            if hasattr(record, key):
                entry[key] = getattr(record, key)
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


def configure_logging() -> None:
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = logging.StreamHandler()
    if (settings.log_format or "text").lower() == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s [%(request_id)s]: %(message)s"))
    handler.addFilter(_RequestIdFilter())
    root.addHandler(handler)
    root.setLevel(getattr(logging, (settings.log_level or "INFO").upper(), logging.INFO))
    for noisy in ("uvicorn.access",):
        logging.getLogger(noisy).setLevel(logging.WARNING)


access_log = logging.getLogger("mclabor.access")


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        offered = request.headers.get("X-Request-ID", "")
        rid = offered if _SAFE_ID.match(offered) else uuid.uuid4().hex[:16]
        token = request_id_var.set(rid)
        t0 = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = rid
        if settings.access_log and not request.url.path.endswith(("/api/health", "/api/ready")):
            request_id_var.set(rid)
            access_log.info("%s %s -> %s in %d ms", request.method, request.url.path, response.status_code, int((time.perf_counter() - t0) * 1000),
                            extra={"method": request.method, "path": request.url.path, "status": response.status_code, "ms": int((time.perf_counter() - t0) * 1000)})
        return response
