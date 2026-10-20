"""Secure-by-default HTTP plumbing for a JSON API: security headers, a request
body size limit, one structured access-log line per request, and generic errors.

Pure ASGI middleware, so it also covers streamed bodies and every route.
Keep this file when you build on the example; tune the constants, do not delete it.
"""

import json
import logging
import sys
import time
from datetime import UTC, datetime

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

# Conservative headers for an API that only returns JSON. TLS terminates at the
# platform edge; HSTS is still correct because every public request arrives over
# HTTPS. No includeSubDomains: the app does not own the parent domain.
SECURITY_HEADERS = {
    b"x-content-type-options": b"nosniff",
    b"x-frame-options": b"DENY",
    b"referrer-policy": b"no-referrer",
    b"content-security-policy": b"default-src 'none'; frame-ancestors 'none'; base-uri 'none'",
    b"strict-transport-security": b"max-age=31536000",
    b"cross-origin-opener-policy": b"same-origin",
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, UTC).isoformat()
        entry = {"ts": ts, "level": record.levelname.lower(), "msg": record.getMessage()}
        entry.update(getattr(record, "fields", {}))
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def _json_handler() -> logging.Handler:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    return handler


def get_logger(name: str) -> logging.Logger:
    """A logger that writes one JSON object per line to stdout (Guidal collects stdout)."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.addHandler(_json_handler())
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


log = get_logger("app")

# uvicorn configures its own plain-text loggers before it imports the app; switch
# them to JSON too, so every line on stdout (startup, shutdown, errors) is one
# JSON object. The access log is off (--no-access-log): the middleware logs requests.
logging.getLogger("uvicorn").handlers = [_json_handler()]


class BodyTooLarge(HTTPException):
    # An HTTPException, so FastAPI's body parsing re-raises it as a 413 instead
    # of wrapping it into a generic 400.
    def __init__(self) -> None:
        super().__init__(status_code=413, detail="request body too large")


class SecureHTTPMiddleware:
    def __init__(self, app, max_body_bytes: int) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        started = time.monotonic()
        status = 500
        response_started = False

        async def send_with_headers(message):
            nonlocal status, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status = message["status"]
                present = {k.lower() for k, _ in message.get("headers", [])}
                extra = [(k, v) for k, v in SECURITY_HEADERS.items() if k not in present]
                message["headers"] = list(message.get("headers", [])) + extra
            await send(message)

        try:
            declared = dict(scope["headers"]).get(b"content-length")
            if declared is not None and (not declared.isdigit() or int(declared) > self.max_body_bytes):
                response = JSONResponse({"detail": "request body too large"}, status_code=413)
                return await response(scope, receive, send_with_headers)

            received = 0

            async def limited_receive():
                nonlocal received
                message = await receive()
                if message["type"] == "http.request":
                    received += len(message.get("body", b""))
                    if received > self.max_body_bytes:
                        raise BodyTooLarge()
                return message

            await self.app(scope, limited_receive, send_with_headers)
        except Exception as exc:
            # Handled here, inside this middleware, so the 500 still carries the security
            # headers. Full detail goes to the logs; the client never sees a traceback.
            log.error("unhandled error", exc_info=exc, extra={"fields": {"path": scope["path"]}})
            if response_started:
                raise  # Too late for a clean 500: let the server drop the connection.
            status = 500
            response = JSONResponse({"detail": "internal server error"}, status_code=500)
            await response(scope, receive, send_with_headers)
        finally:
            # Path only: query strings often carry tokens. Never log headers or bodies.
            log.info(
                "request",
                extra={
                    "fields": {
                        "method": scope["method"],
                        "path": scope["path"],
                        "status": status,
                        "duration_ms": round((time.monotonic() - started) * 1000, 1),
                    }
                },
            )


def secure(app: FastAPI, max_body_bytes: int = 64 * 1024) -> FastAPI:
    app.add_middleware(SecureHTTPMiddleware, max_body_bytes=max_body_bytes)
    return app
