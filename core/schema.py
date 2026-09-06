def add_error_contract(result, generator, request, public):
    """Publish the stable error envelope and correlation headers for API consumers."""
    result.setdefault("components", {}).setdefault("schemas", {})["ErrorEnvelope"] = {
        "type": "object",
        "required": ["error"],
        "properties": {
            "error": {
                "type": "object",
                "required": ["code", "message", "details", "request_id"],
                "properties": {
                    "code": {"type": "string"},
                    "message": {"type": "string"},
                    "details": {"type": "object", "additionalProperties": True},
                    "request_id": {"type": "string", "format": "uuid"},
                },
            },
        },
    }
    for path, operations in result["paths"].items():
        if not path.startswith("/api/v1/"):
            continue
        for method, operation in operations.items():
            if method not in {"get", "post", "patch", "delete"}:
                continue
            responses = operation.setdefault("responses", {})
            codes = {
                400: "Invalid request",
                401: "Authentication required or invalid",
                403: "Forbidden",
                404: "Resource not found",
                429: "Rate limit exceeded",
                500: "Unexpected error",
                503: "Dependency unavailable",
            }
            if method in {"post", "patch", "delete"}:
                codes.update(
                    {
                        409: "State or idempotency conflict",
                        412: "Revision conflict",
                        428: "If-Match required",
                        413: "Payload too large",
                        415: "Unsupported media type",
                    }
                )
            for code, description in codes.items():
                responses.setdefault(
                    str(code),
                    {
                        "description": description,
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/ErrorEnvelope"}
                            }
                        },
                    },
                )
            for response in responses.values():
                response.setdefault("headers", {})["X-Request-ID"] = {
                    "schema": {"type": "string", "format": "uuid"},
                    "description": "Correlation ID shared with audit and job logs.",
                }
    return result
