import json
import logging
import time
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime

request_id_context = ContextVar("request_id", default="")
logger = logging.getLogger("dms.http")


class JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage()
            if record.name.startswith("dms.")
            else str(record.msg)[:200],
            "request_id": getattr(record, "request_id", request_id_context.get()),
        }
        for key in (
            "job_id",
            "document_id",
            "actor_id",
            "status",
            "duration_ms",
            "attempt",
            "error_code",
            "exception_type",
        ):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        # No exception messages, request bodies, tokens, filenames or extracted text.
        # Stack locations remain useful without including arbitrary exception payloads.
        if record.exc_info and record.exc_info[2]:
            import traceback

            payload["exception_type"] = record.exc_info[0].__name__
            payload["stack"] = [
                {
                    "file": frame.filename.rsplit("/", 1)[-1],
                    "line": frame.lineno,
                    "function": frame.name,
                }
                for frame in traceback.extract_tb(record.exc_info[2])
            ]
        return json.dumps(payload, ensure_ascii=False, default=str)


class RequestContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            correlation = str(uuid.UUID(request.headers.get("X-Request-ID", "")))
        except (ValueError, AttributeError):
            correlation = str(uuid.uuid4())
        request.request_id = correlation
        token = request_id_context.set(correlation)
        started = time.monotonic()
        try:
            response = self.get_response(request)
            response["X-Request-ID"] = correlation
            response["Cache-Control"] = "no-store"
            logger.info(
                "request_completed",
                extra={
                    "status": response.status_code,
                    "duration_ms": round((time.monotonic() - started) * 1000),
                },
            )
            return response
        finally:
            request_id_context.reset(token)
