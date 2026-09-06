import logging

from django.core.exceptions import RequestDataTooBig
from django.db import InterfaceError, OperationalError
from django.http import JsonResponse
from redis.exceptions import RedisError
from rest_framework.exceptions import APIException
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger("dms.errors")


class Conflict(APIException):
    status_code = 409
    default_detail = "The operation conflicts with the current resource state."
    default_code = "conflict"


class PreconditionRequired(APIException):
    status_code = 428
    default_detail = 'Provide the current revision in If-Match, for example: "1".'
    default_code = "precondition_required"


class PreconditionFailed(APIException):
    status_code = 412
    default_detail = "The document was modified. Retrieve it again before retrying."
    default_code = "revision_conflict"


class ServiceUnavailable(APIException):
    status_code = 503
    default_detail = "A required service is temporarily unavailable. Please retry later."
    default_code = "service_unavailable"


class PayloadTooLarge(APIException):
    status_code = 413
    default_detail = "The upload exceeds the configured size limit."
    default_code = "payload_too_large"


def exception_handler(exc, context):
    if isinstance(exc, (OperationalError, InterfaceError, RedisError)):
        logger.exception("dependency_unavailable")
        exc = ServiceUnavailable()
    elif isinstance(exc, RequestDataTooBig):
        exc = PayloadTooLarge()
    response = drf_exception_handler(exc, context)
    request = context.get("request")
    correlation = getattr(request, "request_id", "")
    if response is None:
        from rest_framework.response import Response

        logger.exception("unhandled_api_error", extra={"error_code": "internal_error"})
        return Response(
            {
                "error": {
                    "code": "internal_error",
                    "message": "An unexpected error occurred.",
                    "details": {},
                    "request_id": correlation,
                }
            },
            status=500,
        )
    code = getattr(exc, "default_code", "request_error")
    data = response.data
    detail = data.get("detail") if isinstance(data, dict) else None
    message = str(detail) if detail is not None else "Request validation failed."
    response.data = {
        "error": {
            "code": code,
            "message": message,
            "details": {} if detail is not None else data,
            "request_id": correlation,
        }
    }
    if response.status_code >= 500:
        logger.error("service_error", extra={"error_code": code})
    return response


def http_error(request, status, code, message):
    return JsonResponse(
        {
            "error": {
                "code": code,
                "message": message,
                "details": {},
                "request_id": getattr(request, "request_id", ""),
            }
        },
        status=status,
    )


def not_found(request, exception):
    return http_error(request, 404, "not_found", "Resource not found.")


def bad_request(request, exception):
    return http_error(request, 400, "bad_request", "Invalid request.")


def server_error(request):
    return http_error(request, 500, "internal_error", "An unexpected error occurred.")
