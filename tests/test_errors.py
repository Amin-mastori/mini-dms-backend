import json
import logging
import uuid
from unittest.mock import patch

import pytest
import yaml
from redis.exceptions import ConnectionError as RedisConnectionError
from rest_framework.test import APIClient

from core.observability import JsonFormatter

pytestmark = pytest.mark.django_db


def test_request_id_is_propagated_to_error_and_audit(client, upload_file):
    correlation = str(uuid.uuid4())
    response = client.post(
        "/api/v1/documents/", {"title": ""}, format="json", HTTP_X_REQUEST_ID=correlation
    )
    assert response.status_code == 400
    assert response["X-Request-ID"] == correlation
    assert response.data["error"]["request_id"] == correlation
    success = client.post(
        "/api/v1/documents/",
        {"file": upload_file(), "title": "Test"},
        format="multipart",
        HTTP_X_REQUEST_ID=correlation,
    )
    from documents.models import AuditEvent

    assert str(AuditEvent.objects.get(document_id=success.data["id"]).request_id) == correlation


def test_invalid_request_id_is_replaced(client):
    response = client.get("/api/v1/documents/", HTTP_X_REQUEST_ID="untrusted-value")
    uuid.UUID(response["X-Request-ID"])


def test_unhandled_error_is_generic(client):
    with patch(
        "documents.views.DocumentListSerializer",
        side_effect=RuntimeError("secret-connection-string"),
    ):
        response = client.get("/api/v1/documents/")
    assert response.status_code == 500
    assert response.data["error"]["code"] == "internal_error"
    assert "secret-connection-string" not in json.dumps(response.data)


def test_redis_outage_fails_closed_with_503(client):
    with patch(
        "rest_framework.throttling.SimpleRateThrottle.cache.get",
        side_effect=RedisConnectionError("redis password"),
    ):
        response = client.get("/api/v1/documents/")
    assert response.status_code == 503
    assert "redis password" not in json.dumps(response.data)


def test_missing_route_is_json_and_invalid_uuid_is_not_500(client):
    for path in ("/not-a-route/", "/api/v1/documents/------------------------------------/"):
        response = client.get(path)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"


def test_liveness_public_readiness_admin_only(client, admin):
    assert APIClient().get("/health/live/").status_code == 200
    client.force_authenticate(admin)
    assert client.get("/health/ready/").status_code == 200
    with patch("core.health.default_storage.exists", side_effect=OSError("secret")):
        response = client.get("/health/ready/")
    assert response.status_code == 503 and response.data["checks"]["storage"] == "unavailable"


def test_json_log_does_not_include_exception_payload():
    try:
        raise RuntimeError("SECRET-PASSWORD")
    except RuntimeError:
        import sys

        record = logging.LogRecord(
            "dms.jobs", logging.ERROR, __file__, 1, "job_failed", (), sys.exc_info()
        )
    output = JsonFormatter().format(record)
    assert "SECRET-PASSWORD" not in output
    assert json.loads(output)["exception_type"] == "RuntimeError"
    assert json.loads(output)["stack"]


def test_download_outage_safe_error(client, document):
    with patch(
        "documents.views.default_storage.open", side_effect=OSError("sensitive storage url")
    ):
        response = client.get(f"/api/v1/documents/{document.id}/download/")
    assert response.status_code == 503
    assert "sensitive storage url" not in str(response.data)


@pytest.mark.parametrize("url", ["/api/schema/", "/api/docs/", "/api/redoc/"])
def test_api_documentation_is_available(url):
    assert APIClient().get(url).status_code == 200


def test_document_upload_schema_offers_a_binary_multipart_form():
    schema = yaml.safe_load(APIClient().get("/api/schema/").content)
    content = schema["paths"]["/api/v1/documents/"]["post"]["requestBody"]["content"]
    assert list(content) == ["multipart/form-data"]
    reference = content["multipart/form-data"]["schema"]["$ref"].rsplit("/", 1)[-1]
    file_schema = schema["components"]["schemas"][reference]["properties"]["file"]
    assert file_schema == {"type": "string", "format": "binary", "writeOnly": True}
    assert schema["components"]["schemas"][reference]["properties"]["tags"] == {
        "type": "array",
        "items": {"type": "string", "maxLength": 64},
        "maxItems": 32,
    }
    assert schema["components"]["schemas"][reference]["properties"]["metadata"] == {
        "type": "object",
        "additionalProperties": {},
    }


def test_document_response_schema_exposes_json_shapes():
    schema = yaml.safe_load(APIClient().get("/api/schema/").content)
    properties = schema["components"]["schemas"]["Document"]["properties"]
    assert properties["tags"]["type"] == "array"
    assert properties["metadata"]["type"] == "object"
    assert properties["processing_info"]["type"] == "object"


def test_oversized_request_rejected_before_body_parsing(client, settings):
    settings.MAX_UPLOAD_BYTES = 10
    response = client.post("/api/v1/documents/", {"title": "x" * 70000}, format="json")
    assert response.status_code == 413


def test_invalid_search_bytes_are_validation_errors(client):
    assert client.get("/api/v1/documents/", {"q": "\x00"}).status_code == 400
